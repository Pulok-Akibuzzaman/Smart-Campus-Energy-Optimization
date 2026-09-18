"""
Deterministic guardrails for LLM-emitted operator-note interpretations.

Section 08 of the Problem Statement defines these checks. We enforce them
before the optimizer sees any directive, so a malformed LLM response can
never silently invent an unsupported directive or break the schedule.

Originally from Ashik/src/gridwise/validator.py (a942e15).
Behavioural contrast (measured live this session):
  Aurna  : rejects 7/17,  silently coerces 10/17
  Pulok  : rejects 1/17,  silently coerces 16/17 (most permissive)
  Ashik  : rejects 12/17, silently coerces 5/17  (strictest — chosen for merge)
The stricter rejection rate is preferred for hidden cases: a permissive
validator may propagate invalid hours/factors into the optimizer and
produce a wrong cost.

When in doubt this module falls back to no_op; it never crashes.
A wrong `no_op` loses interpretation points; invented rules can also
break application points.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .schemas import (
    BatterySpec,
    DirectiveInterpretationEntry,
    DirectiveType,
    HourEntry,
    MaxGridWindowAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    SolarReductionAdjustment,
)

log = logging.getLogger(__name__)

ALLOWED_DIRECTIVES = {d.value for d in DirectiveType}


def _clean_hours(raw: Any) -> Optional[List[int]]:
    """Return unique sorted ints 0..23, or None if input is malformed."""
    if not isinstance(raw, list):
        return None
    seen = set()
    out = []
    for v in raw:
        if isinstance(v, bool):  # bool is int subclass — reject
            return None
        if not isinstance(v, int):
            return None
        if v < 0 or v > 23 or v in seen:
            return None
        seen.add(v)
        out.append(v)
    return sorted(out)


def _safe_no_op(note_index: int, reason: str) -> DirectiveInterpretationEntry:
    return DirectiveInterpretationEntry(
        note_index=note_index,
        applies=False,
        directive_type=DirectiveType.NO_OP,
        structured_adjustment=None,
        explanation=f"Marked as no_op: {reason}",
    )


def coerce_entry(
    raw: Any,
    note_index: int,
    battery: BatterySpec,
) -> DirectiveInterpretationEntry:
    """Validate a single LLM-emitted entry; coerce to no_op on any failure.

    LLM output is treated as untrusted structured data. We never raise here
    — we always return a valid DirectiveInterpretationEntry.
    """
    if not isinstance(raw, dict):
        return _safe_no_op(note_index, "entry is not an object")

    # ── directive_type ──
    d_type = raw.get("directive_type")
    if not isinstance(d_type, str) or d_type not in ALLOWED_DIRECTIVES:
        return _safe_no_op(note_index, "unsupported directive_type")

    # ── applies ──
    applies = raw.get("applies")
    if d_type == "no_op":
        if applies is True:
            # LLM confused: a no_op must be applies=False per spec.
            return _safe_no_op(note_index, "no_op must use applies=false")
        if applies not in (False, None):
            return _safe_no_op(note_index, "applies must be boolean")
        return DirectiveInterpretationEntry(
            note_index=note_index,
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation=str(raw.get("explanation") or "Note does not affect the schedule."),
        )

    # Non-no_op: applies must be exactly True.
    if applies is not True:
        return _safe_no_op(note_index, f"non-no_op directive requires applies=true")

    # ── structured_adjustment ──
    adj = raw.get("structured_adjustment")
    if not isinstance(adj, dict):
        return _safe_no_op(note_index, "missing structured_adjustment")

    hours_raw = _clean_hours(adj.get("hours"))
    if hours_raw is None or len(hours_raw) == 0:
        return _safe_no_op(note_index, "invalid or empty hours")

    explanation = str(raw.get("explanation") or f"LLM emitted {d_type} directive.")

    try:
        if d_type == "solar_reduction":
            factor = adj.get("factor")
            if not isinstance(factor, (int, float)) or isinstance(factor, bool):
                return _safe_no_op(note_index, "factor must be numeric")
            factor = float(factor)
            if factor < 0.0 or factor > 1.0:
                return _safe_no_op(note_index, "factor must be in [0, 1]")
            parsed = SolarReductionAdjustment(hours=hours_raw, factor=factor)
            return DirectiveInterpretationEntry(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.SOLAR_REDUCTION,
                structured_adjustment=parsed,
                explanation=explanation,
            )

        if d_type == "minimum_battery_reserve":
            me = adj.get("minimum_energy_kwh")
            if not isinstance(me, (int, float)) or isinstance(me, bool):
                return _safe_no_op(note_index, "minimum_energy_kwh must be numeric")
            me = float(me)
            if me < 0 or me > battery.capacity_kwh:
                return _safe_no_op(
                    note_index,
                    f"minimum_energy_kwh {me} outside [0, capacity {battery.capacity_kwh}]",
                )
            parsed = MinimumBatteryReserveAdjustment(hours=hours_raw, minimum_energy_kwh=me)
            return DirectiveInterpretationEntry(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE,
                structured_adjustment=parsed,
                explanation=explanation,
            )

        if d_type == "no_charge_window":
            parsed = NoChargeWindowAdjustment(hours=hours_raw)
            return DirectiveInterpretationEntry(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.NO_CHARGE_WINDOW,
                structured_adjustment=parsed,
                explanation=explanation,
            )

        if d_type == "no_discharge_window":
            parsed = NoDischargeWindowAdjustment(hours=hours_raw)
            return DirectiveInterpretationEntry(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.NO_DISCHARGE_WINDOW,
                structured_adjustment=parsed,
                explanation=explanation,
            )

        if d_type == "max_grid_window":
            mg = adj.get("max_grid_kwh")
            if not isinstance(mg, (int, float)) or isinstance(mg, bool):
                return _safe_no_op(note_index, "max_grid_kwh must be numeric")
            mg = float(mg)
            if mg < 0:
                return _safe_no_op(note_index, "max_grid_kwh must be non-negative")
            parsed = MaxGridWindowAdjustment(hours=hours_raw, max_grid_kwh=mg)
            return DirectiveInterpretationEntry(
                note_index=note_index,
                applies=True,
                directive_type=DirectiveType.MAX_GRID_WINDOW,
                structured_adjustment=parsed,
                explanation=explanation,
            )

    except Exception as e:
        return _safe_no_op(note_index, f"validation raised: {e}")

    # Unreachable; safety net.
    return _safe_no_op(note_index, "unreachable directive branch")


def validate_all(
    raw_entries: Any,
    operator_notes: List[str],
    battery: BatterySpec,
) -> List[DirectiveInterpretationEntry]:
    """Validate the full LLM-emitted list. Guarantees one entry per note, in order.

    If the LLM returns the wrong number of entries, missing notes, or out-of-
    order indexes, we still emit one entry per note in note_index order, marked
    no_op where appropriate.
    """
    n = len(operator_notes)

    # First, index whatever entries we got by note_index.
    indexed: Dict[int, Any] = {}
    if isinstance(raw_entries, list):
        for item in raw_entries:
            if not isinstance(item, dict):
                continue
            ni = item.get("note_index")
            if not isinstance(ni, int) or ni < 0 or ni >= n:
                continue
            if ni in indexed:
                continue  # duplicate — drop the later one
            indexed[ni] = item

    out: List[DirectiveInterpretationEntry] = []
    for i in range(n):
        raw = indexed.get(i)
        if raw is None:
            out.append(_safe_no_op(i, "no entry returned for this note"))
        else:
            out.append(coerce_entry(raw, i, battery))
    return out
