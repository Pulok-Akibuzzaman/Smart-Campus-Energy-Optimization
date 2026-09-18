"""Deterministic Guardrails for LLM Directive Interpretation.

Treats all LLM output as untrusted until verified. Strictly enforces:
- Exactly one entry per operator note, in note_index order (0..N-1)
- Only canonical directive types (solar_reduction, minimum_battery_reserve,
  no_charge_window, no_discharge_window, max_grid_window, no_op)
- applies boolean semantics (False iff no_op, True otherwise)
- Hours array formatting (unique ascending ints 0..23)
- Range constraints on numeric factors, reserves, and caps
- Safe fallback to no_op if any unrecoverable formatting or range issue occurs
"""

import math
from typing import List, Dict, Any, Optional
from app.schemas import DirectiveInterpretationEntry, AllowedDirectiveType

ALLOWED_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
}


def sanitize_hours(raw_hours: Any) -> Optional[List[int]]:
    """Validates and sorts hours into unique ascending ints in [0, 23]."""
    if not isinstance(raw_hours, list):
        return None
    valid_hours = set()
    for h in raw_hours:
        try:
            h_int = int(h)
            if 0 <= h_int <= 23:
                valid_hours.add(h_int)
            else:
                return None
        except (ValueError, TypeError):
            return None
    if not valid_hours:
        return None
    return sorted(list(valid_hours))


def create_safe_noop(index: int, reason: str = "This note does not affect today's 24-hour energy schedule.") -> DirectiveInterpretationEntry:
    return DirectiveInterpretationEntry(
        note_index=index,
        applies=False,
        directive_type="no_op",
        structured_adjustment=None,
        explanation=reason
    )


def validate_and_guardrail_directives(
    raw_directives: Any,
    operator_notes: List[str],
    battery_capacity_kwh: float
) -> List[DirectiveInterpretationEntry]:
    """Deterministically validates, repairs, or falls back LLM directive interpretations."""
    num_notes = len(operator_notes)
    validated_entries: Dict[int, DirectiveInterpretationEntry] = {}

    # Convert raw input to a list if dict was wrapped
    items = []
    if isinstance(raw_directives, list):
        items = raw_directives
    elif isinstance(raw_directives, dict):
        if "directive_interpretation" in raw_directives and isinstance(raw_directives["directive_interpretation"], list):
            items = raw_directives["directive_interpretation"]
        elif "directives" in raw_directives and isinstance(raw_directives["directives"], list):
            items = raw_directives["directives"]
        else:
            items = [raw_directives]

    for item in items:
        if not isinstance(item, dict):
            continue

        try:
            idx = int(item.get("note_index", -1))
        except (ValueError, TypeError):
            continue

        if idx < 0 or idx >= num_notes:
            continue
        if idx in validated_entries:
            # Duplicate mapping detected; first valid or well-formed takes priority
            continue

        directive_type = item.get("directive_type")
        if directive_type not in ALLOWED_TYPES:
            validated_entries[idx] = create_safe_noop(idx, "Unrecognized directive type received; safely treated as no_op.")
            continue

        explanation = str(item.get("explanation") or "").strip()
        if not explanation:
            explanation = f"Interpreted directive of type {directive_type}."

        raw_adj = item.get("structured_adjustment")

        if directive_type == "no_op":
            validated_entries[idx] = DirectiveInterpretationEntry(
                note_index=idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation=explanation or "This note does not affect today's energy schedule."
            )
            continue

        # For all other directives, structured_adjustment must be a dict
        if not isinstance(raw_adj, dict):
            validated_entries[idx] = create_safe_noop(idx, "Missing structured adjustment; safely defaulted to no_op.")
            continue

        # Extract & sanitize hours
        hours = sanitize_hours(raw_adj.get("hours"))
        if hours is None or len(hours) == 0:
            validated_entries[idx] = create_safe_noop(idx, "Invalid or missing hours range; safely defaulted to no_op.")
            continue

        # Specific directive checks
        if directive_type == "solar_reduction":
            factor_raw = raw_adj.get("factor")
            try:
                factor = float(factor_raw)
                if not math.isfinite(factor) or factor < 0.0 or factor > 1.0:
                    # Check if model passed percentage like 20 instead of 0.2
                    if 1.0 < factor <= 100.0:
                        factor = factor / 100.0
                    else:
                        factor = max(0.0, min(1.0, factor))
            except (ValueError, TypeError):
                validated_entries[idx] = create_safe_noop(idx, "Invalid solar factor value; safely defaulted to no_op.")
                continue

            validated_entries[idx] = DirectiveInterpretationEntry(
                note_index=idx,
                applies=True,
                directive_type="solar_reduction",
                structured_adjustment={"hours": hours, "factor": round(factor, 4)},
                explanation=explanation
            )

        elif directive_type == "minimum_battery_reserve":
            val_raw = raw_adj.get("minimum_energy_kwh")
            try:
                val = float(val_raw)
                if not math.isfinite(val) or val < 0.0:
                    validated_entries[idx] = create_safe_noop(idx, "Invalid minimum battery reserve value.")
                    continue
                # Cannot exceed battery capacity
                if val > battery_capacity_kwh:
                    val = battery_capacity_kwh
            except (ValueError, TypeError):
                validated_entries[idx] = create_safe_noop(idx, "Invalid reserve energy value; safely defaulted to no_op.")
                continue

            validated_entries[idx] = DirectiveInterpretationEntry(
                note_index=idx,
                applies=True,
                directive_type="minimum_battery_reserve",
                structured_adjustment={"hours": hours, "minimum_energy_kwh": round(val, 2)},
                explanation=explanation
            )

        elif directive_type == "no_charge_window":
            validated_entries[idx] = DirectiveInterpretationEntry(
                note_index=idx,
                applies=True,
                directive_type="no_charge_window",
                structured_adjustment={"hours": hours},
                explanation=explanation
            )

        elif directive_type == "no_discharge_window":
            validated_entries[idx] = DirectiveInterpretationEntry(
                note_index=idx,
                applies=True,
                directive_type="no_discharge_window",
                structured_adjustment={"hours": hours},
                explanation=explanation
            )

        elif directive_type == "max_grid_window":
            val_raw = raw_adj.get("max_grid_kwh")
            try:
                val = float(val_raw)
                if not math.isfinite(val) or val < 0.0:
                    validated_entries[idx] = create_safe_noop(idx, "Invalid grid cap value; safely defaulted to no_op.")
                    continue
            except (ValueError, TypeError):
                validated_entries[idx] = create_safe_noop(idx, "Invalid grid cap value; safely defaulted to no_op.")
                continue

            validated_entries[idx] = DirectiveInterpretationEntry(
                note_index=idx,
                applies=True,
                directive_type="max_grid_window",
                structured_adjustment={"hours": hours, "max_grid_kwh": round(val, 2)},
                explanation=explanation
            )

    # Ensure every single note index from 0 to N-1 exists exactly once
    final_list: List[DirectiveInterpretationEntry] = []
    for i in range(num_notes):
        if i in validated_entries:
            final_list.append(validated_entries[i])
        else:
            final_list.append(create_safe_noop(i, "No directive extracted for this note; safely defaulted to no_op."))

    return final_list
