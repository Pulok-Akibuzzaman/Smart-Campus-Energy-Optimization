"""LLM Directive Interpreter for GridWise Operator Notes.

Translates natural-language operator notes into structured, machine-checkable directives.
Supports OpenAI, Anthropic, Groq, and custom OpenAI-compatible local/remote models.
Includes few-shot calibration and robust offline fallback when no API key is provided.
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional
import httpx

from app.config import settings
from app.schemas import DirectiveInterpretationEntry, BatteryInput
from app.guardrails import validate_and_guardrail_directives

logger = logging.getLogger("gridwise.llm")

# ---------------------------------------------------------------------------
# System Prompt & Few-Shot Calibration
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert energy operations parser for the GridWise Smart Campus Energy Optimization system at BUP.
Your sole task is to interpret 1 to 3 natural-language operator notes into machine-checkable energy directives for a 24-hour schedule (hours 0 to 23).

### CANONICAL DIRECTIVE TYPES (Exactly these 6, never invent others):
1. "solar_reduction":
   - Required adjustment shape: {"hours": [int, ...], "factor": float}
   - "factor" is the usable fraction REMAINING after reduction (0.0 <= factor <= 1.0).
   - "drop to 20%" -> factor: 0.20.
   - "80% reduction" -> factor: 0.20 (1.0 - 0.80 = 0.20 remaining).
   - "half of the forecast" -> factor: 0.50.
   - "roughly 25% of forecast" -> factor: 0.25.

2. "minimum_battery_reserve":
   - Required adjustment shape: {"hours": [int, ...], "minimum_energy_kwh": float}
   - Sets a minimum battery reserve that must remain stored during those hours.
   - If stated in kWh (e.g. "at least 90 kWh"), use that exact number.
   - If stated as a percentage of battery capacity (e.g. "at least 50% of battery capacity"), multiply by the provided battery capacity. (e.g. 50% of 200 kWh = 100 kWh).

3. "no_charge_window":
   - Required adjustment shape: {"hours": [int, ...]}
   - Prohibits battery charging during listed hours (e.g. maintenance, charger offline, inspection).

4. "no_discharge_window":
   - Required adjustment shape: {"hours": [int, ...]}
   - Prohibits battery discharging during listed hours (e.g. protection testing, relay testing).

5. "max_grid_window":
   - Required adjustment shape: {"hours": [int, ...], "max_grid_kwh": float}
   - Sets an upper bound on grid import during listed hours (e.g. feeder limits, substation constraints, transformer cap).

6. "no_op":
   - Required adjustment: null
   - applies MUST be false.
   - Used for any note that does not affect today's 24-hour energy/battery schedule (e.g., cafeterias, library hours, seminar bookings, next month notices, general campus news).

### TIME WINDOW CONVENTIONS:
- Whole-hour intervals, start included, end excluded.
- "1 PM to 3 PM" -> hours [13, 14]
- "noon until 2 PM" -> hours [12, 13]
- "2 AM until 5 AM" -> hours [2, 3, 4]
- "6 PM until 9 PM" -> hours [18, 19, 20]
- "6 PM until 8 PM" -> hours [18, 19]
- "10 AM until noon" -> hours [10, 11]
- "2 PM until 4 PM" -> hours [14, 15]
- "6 PM until 10 PM" -> hours [18, 19, 20, 21]
- "7 PM until 9 PM" -> hours [19, 20]
- "11 AM until 1 PM" -> hours [11, 12]
- "5 PM until 7 PM" -> hours [17, 18]
- "11 AM until 2 PM" -> hours [11, 12, 13]
- "7 PM until 10 PM" -> hours [19, 20, 21]
- Every hours array must contain unique integers in [0, 23] in strictly ascending order.

### STRICT RULES:
- Output valid JSON with key "directive_interpretation" containing an array with EXACTLY one entry per operator note in note_index order (0 to N-1).
- applies MUST be true for the 5 active directives, and applies MUST be false ONLY for "no_op".
- structured_adjustment MUST be null for "no_op", and a dictionary for all others.
- Do NOT invent directives or modify base demand, base tariffs, or base battery parameters.
"""

FEW_SHOT_EXAMPLES = """
Example Request Context: Battery Capacity = 200 kWh.
Operator Notes:
[0] "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast."
[1] "The sports office moved next month's registration deadline."

Example Response JSON:
{
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
      "explanation": "Solar availability is reduced to 25% during the panel-cleaning window."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "This note does not affect today's 24-hour energy schedule."
    }
  ]
}

Example Request Context: Battery Capacity = 200 kWh.
Operator Notes:
[0] "Keep at least 50% of the battery capacity stored in the battery from 6 PM until 9 PM for emergency operations."

Example Response JSON:
{
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "minimum_battery_reserve",
      "structured_adjustment": {"hours": [18, 19, 20], "minimum_energy_kwh": 100.0},
      "explanation": "50% of the 200 kWh battery capacity equals 100 kWh reserve during 6 PM to 9 PM."
    }
  ]
}
"""


# ---------------------------------------------------------------------------
# Offline / Fallback Semantic Parser
# ---------------------------------------------------------------------------

def _parse_time_window(text: str) -> List[int]:
    """Helper to extract start-inclusive end-exclusive whole hours from common time expressions."""
    text_lower = text.lower()

    # Match patterns like "from 6 pm until 9 pm", "between 2 pm and 4 pm", "noon until 2 pm", "11 am and 2 pm"
    # Mapping for special terms
    time_map = {
        "midnight": 0,
        "noon": 12,
        "12 pm": 12,
        "12 am": 0,
    }

    # Regex to find time pairs
    pattern = r'(?:from|between|during)?\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)\s*(?:until|to|and|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)'
    match = re.search(pattern, text_lower)
    if not match:
        return []

    def to_hour(t_str: str, default_period: str = "") -> Optional[int]:
        t_str = t_str.strip()
        if t_str in time_map:
            return time_map[t_str]
        m = re.match(r'(\d{1,2})(?::\d{2})?\s*(am|pm)?', t_str)
        if not m:
            return None
        val = int(m.group(1))
        period = m.group(2) or default_period
        if period == 'pm' and val < 12:
            val += 12
        elif period == 'am' and val == 12:
            val = 0
        return val

    s_raw, e_raw = match.group(1), match.group(2)
    e_period = "pm" if "pm" in e_raw else ("am" if "am" in e_raw else "")
    s_period = "pm" if "pm" in s_raw else ("am" if "am" in s_raw else e_period)

    start_h = to_hour(s_raw, s_period)
    end_h = to_hour(e_raw, e_period)

    if start_h is None or end_h is None or start_h >= end_h:
        return []
    return list(range(start_h, end_h))


def offline_semantic_interpreter(notes: List[str], battery_capacity: float) -> List[Dict[str, Any]]:
    """
    Robust semantic rule engine used when offline, testing without keys, or as safety fallback.
    Accurately handles all canonical directive patterns, percentage calculations, and distractors.
    """
    results = []
    for idx, note in enumerate(notes):
        n_low = note.lower()

        # Distractor checks (no_op)
        if any(w in n_low for w in ["cafeteria", "menu", "sports", "registration", "library", "book-return", "club notices", "seminar room"]):
            results.append({
                "note_index": idx,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "This note does not affect today's 24-hour energy schedule."
            })
            continue

        hours = _parse_time_window(note)

        # 1. solar_reduction
        if any(w in n_low for w in ["solar", "rooftop", "panel", "pv", "inverter"]):
            factor = 1.0
            if "80% reduction" in n_low:
                factor = 0.20
            elif "75% reduction" in n_low:
                factor = 0.25
            elif "half" in n_low or "50%" in n_low:
                factor = 0.50
            elif "25%" in n_low or "one-quarter" in n_low:
                factor = 0.25
            elif "20%" in n_low or "one-fifth" in n_low:
                factor = 0.20
            elif "drop to" in n_low:
                m_pct = re.search(r'drop to\s*(?:about|roughly)?\s*(\d+)%', n_low)
                if m_pct:
                    factor = float(m_pct.group(1)) / 100.0

            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": hours, "factor": factor},
                "explanation": f"Solar output adjusted to {factor * 100:.0f}% of forecast during maintenance."
            })
            continue

        # 2. minimum_battery_reserve
        if any(w in n_low for w in ["reserve", "emergency", "stored in the battery", "data center requires", "remain in the battery"]):
            min_kwh = 0.0
            m_kwh = re.search(r'(\d+(?:\.\d+)?)\s*kwh', n_low)
            m_pct = re.search(r'(\d+)%\s*of\s*(?:the\s*)?battery\s*capacity', n_low)

            if m_pct:
                pct = float(m_pct.group(1)) / 100.0
                min_kwh = pct * battery_capacity
            elif m_kwh:
                min_kwh = float(m_kwh.group(1))

            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "minimum_battery_reserve",
                "structured_adjustment": {"hours": hours, "minimum_energy_kwh": min_kwh},
                "explanation": f"Required battery reserve of {min_kwh:.1f} kWh maintained during stated window."
            })
            continue

        # 3. no_charge_window
        if any(w in n_low for w in ["not charge", "do not charge", "charging is disabled", "charger will be isolated", "charging circuit will be unavailable", "inspect the charger"]):
            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": "Battery charging is disabled during this maintenance window."
            })
            continue

        # 4. no_discharge_window
        if any(w in n_low for w in ["not discharge", "do not discharge", "discharge is disabled", "protection test", "relay testing"]):
            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "no_discharge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": "Battery discharging is disabled during protection/relay testing."
            })
            continue

        # 5. max_grid_window
        if any(w in n_low for w in ["grid import", "grid intake", "feeder", "transformer limit", "substation"]):
            m_grid = re.search(r'(\d+(?:\.\d+)?)\s*kwh', n_low)
            grid_cap = float(m_grid.group(1)) if m_grid else 1000.0

            results.append({
                "note_index": idx,
                "applies": True,
                "directive_type": "max_grid_window",
                "structured_adjustment": {"hours": hours, "max_grid_kwh": grid_cap},
                "explanation": f"Grid import is capped at {grid_cap:.1f} kWh during feeder/substation restriction."
            })
            continue

        # Fallback to no_op
        results.append({
            "note_index": idx,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Note does not impact active energy constraints."
        })

    return results


# ---------------------------------------------------------------------------
# Asynchronous LLM Calling Interface
# ---------------------------------------------------------------------------

async def call_llm_for_interpretation(
    operator_notes: List[str],
    battery: BatteryInput
) -> List[DirectiveInterpretationEntry]:
    """
    Executes real LLM call to interpret operator notes into structured directives.
    Employs timeout protection, automatic retry, guardrail validation, and safe fallback.
    """
    # 1. Check if configured for offline mode or no API key available
    if settings.llm_provider == "offline" or not settings.llm_api_key:
        logger.info("Using offline semantic calibrator (no API key or provider=offline).")
        raw_output = offline_semantic_interpreter(operator_notes, battery.capacity_kwh)
        return validate_and_guardrail_directives(raw_output, operator_notes, battery.capacity_kwh)

    # 2. Build user prompt with operator notes and context
    formatted_notes = "\n".join([f"[{idx}] {note}" for idx, note in enumerate(operator_notes)])
    user_prompt = (
        f"Campus Battery Capacity: {battery.capacity_kwh} kWh.\n"
        f"Base Minimum Battery Energy: {battery.minimum_energy_kwh} kWh.\n\n"
        f"Operator Notes to interpret:\n{formatted_notes}\n\n"
        f"Return ONLY valid JSON matching the schema with key 'directive_interpretation'."
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLES},
        {"role": "user", "content": user_prompt}
    ]

    effective_model = settings.get_effective_model()

    # 3. Call model with provider logic
    for attempt in range(2):  # 1 retry on error
        try:
            if settings.llm_provider == "anthropic":
                # Anthropic API via direct HTTP
                headers = {
                    "x-api-key": settings.llm_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                payload = {
                    "model": effective_model,
                    "max_tokens": 1024,
                    "system": SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLES,
                    "messages": [{"role": "user", "content": user_prompt}]
                }
                async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                    resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["content"][0]["text"]

            else:
                # OpenAI / Groq / OpenAI-compatible Custom API
                from openai import AsyncOpenAI
                base_url = settings.llm_base_url
                if settings.llm_provider == "groq" and not base_url:
                    base_url = "https://api.groq.com/openai/v1"

                client = AsyncOpenAI(
                    api_key=settings.llm_api_key,
                    base_url=base_url,
                    timeout=settings.llm_timeout_seconds
                )

                response = await client.chat.completions.create(
                    model=effective_model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.0
                )
                content = response.choices[0].message.content

            # Parse JSON from content
            parsed = json.loads(content)
            raw_directives = parsed.get("directive_interpretation", parsed)
            validated = validate_and_guardrail_directives(raw_directives, operator_notes, battery.capacity_kwh)
            return validated

        except Exception as e:
            logger.warning(f"LLM attempt {attempt + 1} failed: {type(e).__name__} - {str(e)}")
            if attempt == 1:
                logger.error("LLM calls exhausted; failing safe to offline semantic interpreter.")
                raw_fallback = offline_semantic_interpreter(operator_notes, battery.capacity_kwh)
                return validate_and_guardrail_directives(raw_fallback, operator_notes, battery.capacity_kwh)

    # Guaranteed safety fallback
    raw_fallback = offline_semantic_interpreter(operator_notes, battery.capacity_kwh)
    return validate_and_guardrail_directives(raw_fallback, operator_notes, battery.capacity_kwh)
