"""
Validator / guardrails unit tests.

Exercises `coerce_entry` and `validate_all` against hand-rolled bad input.
Per Section 08 of the Problem Statement, every malformed LLM entry must be
coerced to `no_op` — never crashed, never silently shipped.

Run: PYTHONPATH=src python -m pytest tests/test_validator.py -v
     (or simply `python tests/test_validator.py`)
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gridwise.schemas import BatterySpec, DirectiveType  # noqa: E402
from gridwise.validator import coerce_entry, validate_all  # noqa: E402


BATTERY = BatterySpec(
    capacity_kwh=500.0,
    initial_energy_kwh=200.0,
    minimum_energy_kwh=50.0,
    max_charge_kwh_per_hour=100.0,
    max_discharge_kwh_per_hour=100.0,
)


# ─────────────────────── coerce_entry — good inputs ──────────────────


def test_solar_reduction_valid():
    raw = {"applies": True, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [10, 11], "factor": 0.2}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.applies is True
    assert e.directive_type == DirectiveType.SOLAR_REDUCTION
    assert e.structured_adjustment.factor == 0.2
    assert e.structured_adjustment.hours == [10, 11]


def test_no_discharge_window_valid():
    raw = {"applies": True, "directive_type": "no_discharge_window", "structured_adjustment": {"hours": [18, 19]}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.applies is True
    assert e.directive_type == DirectiveType.NO_DISCHARGE_WINDOW
    assert e.structured_adjustment.hours == [18, 19]


def test_no_op_valid():
    raw = {"applies": False, "directive_type": "no_op", "structured_adjustment": None}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.applies is False
    assert e.directive_type == DirectiveType.NO_OP
    assert e.structured_adjustment is None


# ─────────────────────── coerce_entry — bad inputs (coerce to no_op) ──


def test_not_a_dict():
    e = coerce_entry("not a dict", note_index=0, battery=BATTERY)
    assert e.directive_type == DirectiveType.NO_OP and e.applies is False


def test_unknown_directive_type():
    raw = {"directive_type": "launch_missiles", "structured_adjustment": {}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.directive_type == DirectiveType.NO_OP


def test_solar_factor_out_of_range():
    raw = {"directive_type": "solar_reduction", "structured_adjustment": {"hours": [10], "factor": 1.5}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.directive_type == DirectiveType.NO_OP


def test_solar_factor_negative():
    raw = {"directive_type": "solar_reduction", "structured_adjustment": {"hours": [10], "factor": -0.1}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.directive_type == DirectiveType.NO_OP


def test_hours_out_of_range():
    raw = {"directive_type": "solar_reduction", "structured_adjustment": {"hours": [25], "factor": 0.5}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.directive_type == DirectiveType.NO_OP


def test_hours_duplicate():
    raw = {"directive_type": "no_charge_window", "structured_adjustment": {"hours": [5, 5, 6]}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.directive_type == DirectiveType.NO_OP


def test_hours_not_int():
    raw = {"directive_type": "no_charge_window", "structured_adjustment": {"hours": ["5", 6]}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.directive_type == DirectiveType.NO_OP


def test_minimum_battery_reserve_above_capacity():
    raw = {"directive_type": "minimum_battery_reserve",
           "structured_adjustment": {"hours": [10], "minimum_energy_kwh": 9999}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    assert e.directive_type == DirectiveType.NO_OP


def test_applies_must_be_consistent_with_no_op():
    """If LLM marks something as no_op with structured_adjustment != null, coerce."""
    raw = {"applies": False, "directive_type": "no_op", "structured_adjustment": {"hours": [5]}}
    e = coerce_entry(raw, note_index=0, battery=BATTERY)
    # Per spec: no_op MUST have null structured_adjustment; otherwise treat as
    # malformed and coerce.
    assert e.directive_type == DirectiveType.NO_OP
    assert e.structured_adjustment is None


# ─────────────────────── validate_all — list-level invariants ────────


def test_validate_all_preserves_note_order():
    raws = [
        {"note_index": 0, "applies": True, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [10], "factor": 0.5}},
        {"note_index": 1, "applies": False, "directive_type": "no_op", "structured_adjustment": None},
        {"note_index": 2, "applies": True, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [2, 3]}},
    ]
    notes = ["Solar drops 50% at 10.", "Cafeteria menu changes.", "No charge at 2-3."]
    out = validate_all(raw_entries=raws, operator_notes=notes, battery=BATTERY)
    assert len(out) == 3
    assert out[0].directive_type == DirectiveType.SOLAR_REDUCTION
    assert out[1].directive_type == DirectiveType.NO_OP
    assert out[2].directive_type == DirectiveType.NO_CHARGE_WINDOW


def test_validate_all_handles_empty_list():
    out = validate_all(raw_entries=[], operator_notes=["anything"], battery=BATTERY)
    assert len(out) == 1
    assert out[0].directive_type == DirectiveType.NO_OP


def test_validate_all_handles_mixed_malformed():
    """Even when most entries are bad, the function returns a list of valid entries."""
    raws = [
        "garbage",
        {"note_index": 1, "applies": True, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [10], "factor": 0.5}},
        None,
        42,
        {"note_index": 4, "applies": True, "directive_type": "made_up_type", "structured_adjustment": {}},
    ]
    notes = ["n0", "n1", "n2", "n3", "n4"]
    out = validate_all(raw_entries=raws, operator_notes=notes, battery=BATTERY)
    assert len(out) == 5
    # n1 is the only valid one
    assert out[0].directive_type == DirectiveType.NO_OP
    assert out[1].directive_type == DirectiveType.SOLAR_REDUCTION
    assert out[2].directive_type == DirectiveType.NO_OP
    assert out[3].directive_type == DirectiveType.NO_OP
    assert out[4].directive_type == DirectiveType.NO_OP


def test_validate_all_missing_note_index_gets_no_op():
    """Missing notes get no_op rather than crashing."""
    raws = [{"note_index": 0, "applies": True, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [5]}}]
    notes = ["n0", "n1", "n2"]  # 3 notes but only 1 entry
    out = validate_all(raw_entries=raws, operator_notes=notes, battery=BATTERY)
    assert len(out) == 3
    assert out[0].directive_type == DirectiveType.NO_CHARGE_WINDOW
    assert out[1].directive_type == DirectiveType.NO_OP
    assert out[2].directive_type == DirectiveType.NO_OP


def test_validate_all_duplicate_note_index_keeps_first():
    raws = [
        {"note_index": 0, "applies": True, "directive_type": "solar_reduction", "structured_adjustment": {"hours": [10], "factor": 0.5}},
        {"note_index": 0, "applies": True, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [2]}},
    ]
    notes = ["n0"]
    out = validate_all(raw_entries=raws, operator_notes=notes, battery=BATTERY)
    assert len(out) == 1
    assert out[0].directive_type == DirectiveType.SOLAR_REDUCTION  # first wins


# ─────────────────────── Runner ───────────────────────────────────────


def _run_all() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERR   {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{passed + failed} tests passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
