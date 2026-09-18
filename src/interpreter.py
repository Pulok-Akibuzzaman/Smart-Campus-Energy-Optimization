"""
interpreter.py - LLM-Assisted Operator Directive Interpretation Engine
Supports Google Gemini, OpenAI/Groq, and fallback deterministic semantic extraction.
"""

import os
import json
import re
import requests
from typing import List, Dict, Any, Optional
try:
    from src.guardrails import validate_and_sanitize_interpretation
except ImportError:
    from guardrails import validate_and_sanitize_interpretation

SYSTEM_PROMPT = """You are an expert energy operations assistant for a smart university campus microgrid.
Your task is to analyze 1 to 3 natural-language operator notes and extract machine-checkable directives for a 24-hour energy optimization schedule (hours 0 through 23).

The supported directive types are:
1. solar_reduction:
   - Reduces usable solar generation during specific hours.
   - structured_adjustment: {"hours": [int, ...], "factor": float}
   - IMPORTANT: factor is the USABLE FRACTION that remains (e.g., 80% reduction means factor = 0.20; 25% of forecast means factor = 0.25; half output means factor = 0.50).
2. minimum_battery_reserve:
   - Sets a minimum battery reserve energy level in kWh during specific hours.
   - structured_adjustment: {"hours": [int, ...], "minimum_energy_kwh": float}
   - If stated as a percentage of battery capacity (e.g., 50% of battery capacity), multiply that fraction by capacity_kwh.
3. no_charge_window:
   - Battery charging is disabled/unavailable during specific hours.
   - structured_adjustment: {"hours": [int, ...]}
4. no_discharge_window:
   - Battery discharging is disabled/unavailable during specific hours.
   - structured_adjustment: {"hours": [int, ...]}
5. max_grid_window:
   - Campus grid import is capped at a stated limit (kWh) during specific hours.
   - structured_adjustment: {"hours": [int, ...], "max_grid_kwh": float}
6. no_op:
   - The note is a distractor, informational note, or does not affect the 24-hour energy schedule.
   - applies MUST be false, structured_adjustment MUST be null.

CRITICAL TIME CONVENTION:
- Hours are whole-hour intervals: 0 through 23.
- Time ranges are start-inclusive and end-exclusive!
  - "1 PM to 3 PM" -> [13, 14]
  - "noon until 2 PM" -> [12, 13]
  - "6 PM until 9 PM" -> [18, 19, 20]
  - "from 10 AM until noon" -> [10, 11]
  - "from 2 AM until 5 AM" -> [2, 3, 4]
  - "between 11 AM and 2 PM" -> [11, 12, 13]
- Output hours must be a unique, sorted ascending array of integers between 0 and 23.

OUTPUT FORMAT:
Return a JSON array containing exactly one object per note, in note_index order:
[
  {
    "note_index": 0,
    "applies": true,
    "directive_type": "<directive_type>",
    "structured_adjustment": {...} or null,
    "explanation": "<brief explanation>"
  }
]
"""

def parse_time_window(text: str) -> List[int]:
    """
    Extracts start-inclusive, end-exclusive hours from natural language text.
    Handles 'from X until Y', 'between X and Y', 'X to Y', 'noon', 'midnight'.
    """
    text_lower = text.lower()
    
    def parse_hour_str(h_str: str, default_period: Optional[str] = None) -> Optional[int]:
        h_str = h_str.strip()
        if "noon" in h_str:
            return 12
        if "midnight" in h_str:
            return 0
        match = re.search(r"(\d+)(?::00)?\s*(am|pm)?", h_str)
        if not match:
            return None
        val = int(match.group(1))
        period = match.group(2) or default_period
        if period == "pm" and val < 12:
            val += 12
        elif period == "am" and val == 12:
            val = 0
        return val

    # Patterns like: from <start> until/to <end>, between <start> and <end>, <start> - <end>
    patterns = [
        r"(?:from|between)\s+([0-9]+(?::00)?\s*(?:am|pm)?|noon|midnight)\s+(?:until|to|and|-)\s+([0-9]+(?::00)?\s*(?:am|pm)?|noon|midnight)",
        r"([0-9]+(?::00)?\s*(?:am|pm)?)\s+(?:until|to|-)\s+([0-9]+(?::00)?\s*(?:am|pm)?)",
        r"([0-9]+)-([0-9]+)\s*(am|pm)\s+window"
    ]
    
    start_h, end_h = None, None
    for pat in patterns:
        m = re.search(pat, text_lower)
        if m:
            g = m.groups()
            if len(g) == 3 and g[2] in ("am", "pm"): # e.g. 1-3 PM window
                period = g[2]
                start_h = parse_hour_str(g[0], period)
                end_h = parse_hour_str(g[1], period)
            else:
                end_str = g[1]
                end_period = "pm" if "pm" in end_str else ("am" if "am" in end_str else None)
                start_h = parse_hour_str(g[0], end_period)
                end_h = parse_hour_str(g[1], end_period)
            break
            
    # 24-hour format e.g. 13:00 and 15:00
    if start_h is None:
        m24 = re.search(r"(\d{1,2}):00\s*(?:and|to|until|-)\s*(\d{1,2}):00", text_lower)
        if m24:
            start_h = int(m24.group(1))
            end_h = int(m24.group(2))
            
    if start_h is not None and end_h is not None:
        if end_h > start_h and 0 <= start_h < 24 and end_h <= 24:
            return list(range(start_h, end_h))
            
    return []

def fallback_heuristic_interpret(note: str, note_index: int, battery_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic NLP parser used as a safety fallback when no external LLM API is available.
    """
    text = note.strip()
    text_lower = text.lower()
    
    cap = float(battery_data.get("capacity_kwh", 200.0))
    hours = parse_time_window(text_lower)
    
    # 1. Distractors / non-energy notes
    distractor_keywords = ["cafeteria", "sports office", "library", "student affairs", "seminar room", "registration deadline", "club notice", "menu"]
    if any(dk in text_lower for dk in distractor_keywords) or not hours:
        return {
            "note_index": note_index,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": f"Note does not affect 24-hour campus energy dispatch."
        }
        
    # 2. Solar reduction
    if any(k in text_lower for k in ["solar", "pv", "photovoltaic", "panels"]):
        factor = 0.5
        # Check for reduction percent e.g. "80% reduction"
        red_match = re.search(r"(\d+)%\s+reduction", text_lower)
        if red_match:
            factor = round(1.0 - float(red_match.group(1)) / 100.0, 4)
        else:
            # Check for remaining percent e.g. "about 20%", "roughly 25%"
            pct_match = re.search(r"(?:about|roughly|to)?\s*(\d+)%", text_lower)
            if pct_match:
                factor = round(float(pct_match.group(1)) / 100.0, 4)
            elif "half" in text_lower or "one-half" in text_lower:
                factor = 0.5
            elif "one-fifth" in text_lower:
                factor = 0.2
            elif "one-quarter" in text_lower or "fourth" in text_lower:
                factor = 0.25
                
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "solar_reduction",
            "structured_adjustment": {"hours": hours, "factor": factor},
            "explanation": f"Usable solar reduced to {int(factor*100)}% during window."
        }
        
    # 3. No charge window
    if any(k in text_lower for k in ["charger", "charging"]) and any(k in text_lower for k in ["isolated", "disabled", "unavailable", "do not charge", "outage"]):
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": f"Battery charging is disabled during maintenance window."
        }
        
    # 4. No discharge window
    if any(k in text_lower for k in ["discharge", "discharging"]) and any(k in text_lower for k in ["not discharge", "disabled", "unavailable", "relay testing", "protection test"]):
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "no_discharge_window",
            "structured_adjustment": {"hours": hours},
            "explanation": f"Battery discharging is disabled during testing window."
        }
        
    # 5. Max grid window
    if any(k in text_lower for k in ["grid import", "grid intake", "feeder", "transformer", "substation", "grid limit"]):
        cap_match = re.search(r"(\d+(?:\.\d+)?)\s*kwh", text_lower)
        max_grid = float(cap_match.group(1)) if cap_match else 150.0
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "max_grid_window",
            "structured_adjustment": {"hours": hours, "max_grid_kwh": max_grid},
            "explanation": f"Grid import is capped at {max_grid} kWh during window."
        }
        
    # 6. Minimum battery reserve
    if any(k in text_lower for k in ["reserve", "remain in the battery", "stored in the battery", "keep at least"]):
        # Check percentage e.g. "50% of the battery capacity"
        pct_match = re.search(r"(\d+)%\s+of\s+(?:the\s+)?battery\s+capacity", text_lower)
        if pct_match:
            pct = float(pct_match.group(1)) / 100.0
            min_e = round(pct * cap, 4)
        else:
            kwh_match = re.search(r"(\d+(?:\.\d+)?)\s*kwh", text_lower)
            min_e = float(kwh_match.group(1)) if kwh_match else float(battery_data.get("minimum_energy_kwh", 50.0))
        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": "minimum_battery_reserve",
            "structured_adjustment": {"hours": hours, "minimum_energy_kwh": min_e},
            "explanation": f"Battery reserve minimum set to {min_e} kWh during window."
        }
        
    return {
        "note_index": note_index,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "No applicable directive recognized; treated as no_op."
    }

def call_gemini_api(prompt: str, api_key: str) -> Optional[List[Dict[str, Any]]]:
    """Calls Gemini 2.5 Flash via REST API with response_mime_type application/json."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.0
        }
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code == 200:
            res_json = resp.json()
            cand_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(cand_text)
    except Exception as e:
        print(f"[Gemini API Warning] LLM call failed: {e}")
    return None

def call_openai_api(prompt: str, api_key: str, base_url: str = "https://api.openai.com/v1") -> Optional[List[Dict[str, Any]]]:
    """Calls OpenAI-compatible endpoint with JSON response format."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "directives" in parsed:
                return parsed["directives"]
            elif isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                # May be dictionary with list values
                for v in parsed.values():
                    if isinstance(v, list): return v
    except Exception as e:
        print(f"[OpenAI API Warning] LLM call failed: {e}")
    return None

def interpret_operator_notes(
    operator_notes: List[str],
    battery_data: Dict[str, Any],
    scenario_id: str = ""
) -> List[Dict[str, Any]]:
    """
    Interprets operator notes into machine-checkable directives.
    Workflow:
      1. If GEMINI_API_KEY is present, queries Gemini 2.5 Flash.
      2. If OPENAI_API_KEY is present, queries OpenAI/Groq model.
      3. If no key or API fails, uses deterministic semantic fallback parser.
      4. Passes through deterministic guardrails to guarantee 100% schema compliance.
    """
    raw_results = None
    
    # Check for API keys
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY")
    
    user_prompt = f"""Scenario: {scenario_id}
Battery Parameters:
- capacity_kwh: {battery_data.get('capacity_kwh')}
- initial_energy_kwh: {battery_data.get('initial_energy_kwh')}
- minimum_energy_kwh: {battery_data.get('minimum_energy_kwh')}

Operator Notes to interpret:
{json.dumps([{"note_index": i, "text": note} for i, note in enumerate(operator_notes)], indent=2)}

Please return the JSON array of directive interpretations in note_index order."""

    if gemini_key:
        full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"
        raw_results = call_gemini_api(full_prompt, gemini_key)
        
    if raw_results is None and openai_key:
        base_url = "https://api.groq.com/openai/v1" if os.getenv("GROQ_API_KEY") else os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        raw_results = call_openai_api(user_prompt, openai_key, base_url)
        
    # If LLM returned valid list, pass to guardrails
    if raw_results and isinstance(raw_results, list):
        return validate_and_sanitize_interpretation(raw_results, operator_notes, battery_data)
        
    # Controlled fallback: Parse using semantic parser
    fallback_results = []
    for idx, note in enumerate(operator_notes):
        fallback_results.append(fallback_heuristic_interpret(note, idx, battery_data))
        
    return validate_and_sanitize_interpretation(fallback_results, operator_notes, battery_data)
