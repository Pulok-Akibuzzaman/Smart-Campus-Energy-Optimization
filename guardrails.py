"""
guardrails.py - Deterministic Guardrail Validator and Sanitizer
Enforces canonical rules defined in Section 04, 05, and 08 of the Problem Statement.
"""

from typing import List, Dict, Any, Optional

ALLOWED_DIRECTIVES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
}

def sanitize_hours(raw_hours: Any) -> List[int]:
    """
    Ensures hours are unique integers from 0 through 23 in ascending order.
    """
    if not isinstance(raw_hours, list):
        return []
    valid_hours = set()
    for h in raw_hours:
        try:
            ih = int(round(float(h)))
            if 0 <= ih <= 23:
                valid_hours.add(ih)
        except (ValueError, TypeError):
            continue
    return sorted(list(valid_hours))

def validate_and_sanitize_interpretation(
    raw_interpretations: Any,
    operator_notes: List[str],
    battery_data: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Validates and deterministically normalizes the LLM interpretation output.
    Guarantees:
      - Exactly one entry per operator note in note_index order (0..N-1).
      - Applies semantics: applies == False iff directive_type == "no_op".
      - structured_adjustment shape and numeric constraints.
      - Never crashes the server on malformed or adversarial LLM output.
    """
    n_notes = len(operator_notes)
    cleaned_by_index: Dict[int, Dict[str, Any]] = {}
    
    cap = float(battery_data.get("capacity_kwh", 1000.0))
    base_min = float(battery_data.get("minimum_energy_kwh", 0.0))
    
    if isinstance(raw_interpretations, list):
        for item in raw_interpretations:
            if not isinstance(item, dict):
                continue
            idx = item.get("note_index")
            try:
                idx = int(idx)
            except (ValueError, TypeError):
                continue
                
            if not (0 <= idx < n_notes):
                continue
                
            dtype = str(item.get("directive_type", "")).strip().lower()
            if dtype not in ALLOWED_DIRECTIVES:
                dtype = "no_op"
                
            applies = bool(item.get("applies", False))
            explanation = str(item.get("explanation", "")).strip()
            if not explanation:
                explanation = f"Interpretation for operator note {idx}."
                
            adj = item.get("structured_adjustment")
            
            # Canonical applies semantics
            if dtype == "no_op":
                cleaned_by_index[idx] = {
                    "note_index": idx,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": explanation
                }
                continue
                
            # If not no_op, applies must be True
            if not isinstance(adj, dict):
                adj = {}
                
            hours = sanitize_hours(adj.get("hours", []))
            # If hours is empty for a window directive, fallback to no_op
            if not hours:
                cleaned_by_index[idx] = {
                    "note_index": idx,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": f"Note {idx} produced no valid hours; defaulted to no_op."
                }
                continue
                
            cleaned_adj: Dict[str, Any] = {"hours": hours}
            
            if dtype == "solar_reduction":
                try:
                    factor = float(adj.get("factor", 1.0))
                except (ValueError, TypeError):
                    factor = 1.0
                # Clamp factor between 0.0 and 1.0
                factor = max(0.0, min(1.0, factor))
                cleaned_adj["factor"] = round(factor, 4)
                
            elif dtype == "minimum_battery_reserve":
                try:
                    req_min = float(adj.get("minimum_energy_kwh", base_min))
                except (ValueError, TypeError):
                    req_min = base_min
                # Reserve must be finite, non-negative, and <= battery capacity
                req_min = max(0.0, min(cap, req_min))
                cleaned_adj["minimum_energy_kwh"] = round(req_min, 4)
                
            elif dtype == "max_grid_window":
                try:
                    mg = float(adj.get("max_grid_kwh", 1e9))
                except (ValueError, TypeError):
                    mg = 0.0
                mg = max(0.0, mg)
                cleaned_adj["max_grid_kwh"] = round(mg, 4)
                
            elif dtype in ("no_charge_window", "no_discharge_window"):
                pass  # only 'hours' required
                
            cleaned_by_index[idx] = {
                "note_index": idx,
                "applies": True,
                "directive_type": dtype,
                "structured_adjustment": cleaned_adj,
                "explanation": explanation
            }
            
    # Guarantee every index 0..N-1 exists
    final_list: List[Dict[str, Any]] = []
    for i in range(n_notes):
        if i in cleaned_by_index:
            final_list.append(cleaned_by_index[i])
        else:
            final_list.append({
                "note_index": i,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": f"Operator note {i} does not affect the 24-hour schedule."
            })
            
    return final_list
