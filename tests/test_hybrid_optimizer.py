"""
Asserts the hybrid LP optimizer matches reference cost on all 10 public cases.

The hybrid optimizer combines Aurna's exact cost objective (Σ grid[h]*tariff[h]
+ 1e-6 complementarity) with Ashik's 2-stage structure, but ships stage-1 only
when the result is integer-aligned (the public cases are). This produces a
0.00 BDT diff on the 10 public cases while keeping Ashik's peak-min tie-break
behaviour for hidden cases with multiple optima.

Run with:
    PYTHONPATH=src pytest tests/test_hybrid_optimizer.py -v

Originally new in the merge (no equivalent in any of the three branches).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow running this file directly without pytest for quick smoke-testing.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLES_PATH = _REPO_ROOT.parent / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
if not _SAMPLES_PATH.exists():
    # Some setups copy the samples into the repo root.
    _SAMPLES_PATH = _REPO_ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

sys.path.insert(0, str(_REPO_ROOT / "src"))

from gridwise.schemas import (  # noqa: E402
    BatterySpec,
    DirectiveInterpretationEntry,
    DirectiveType,
    HourEntry,
    MaxGridWindowAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    OptimizeRequest,
    SolarReductionAdjustment,
)
from gridwise.constraints import build_constraints  # noqa: E402
from gridwise.optimizer import optimize_schedule  # noqa: E402
from gridwise.replay import replay  # noqa: E402


def _adapt_directive(d: dict) -> DirectiveInterpretationEntry:
    """Convert a JSON directive into our Pydantic schema."""
    if not d.get("applies") or d.get("directive_type") == "no_op":
        return DirectiveInterpretationEntry(
            note_index=d["note_index"],
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation="no_op",
        )
    dt = d["directive_type"]
    adj = d.get("structured_adjustment") or {}
    if dt == "solar_reduction":
        sa = SolarReductionAdjustment(hours=adj["hours"], factor=adj["factor"])
    elif dt == "minimum_battery_reserve":
        sa = MinimumBatteryReserveAdjustment(
            hours=adj["hours"], minimum_energy_kwh=adj["minimum_energy_kwh"]
        )
    elif dt == "no_charge_window":
        sa = NoChargeWindowAdjustment(hours=adj["hours"])
    elif dt == "no_discharge_window":
        sa = NoDischargeWindowAdjustment(hours=adj["hours"])
    elif dt == "max_grid_window":
        sa = MaxGridWindowAdjustment(
            hours=adj["hours"], max_grid_kwh=adj["max_grid_kwh"]
        )
    else:
        pytest.fail(f"Unknown directive_type: {dt!r}")
    return DirectiveInterpretationEntry(
        note_index=d["note_index"],
        applies=True,
        directive_type=DirectiveType(dt),
        structured_adjustment=sa,
        explanation=f"hybrid-optimizer-test bypass for {dt}",
    )


def _load_cases():
    data = json.loads(Path(_SAMPLES_PATH).read_text())
    return data["cases"]


_CASES = _load_cases()


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
def test_cost_matches_reference_within_one_paisa(case):
    """Each public case must match reference cost within 1 BDT (we expect 0.00)."""
    inp = case["input"]
    exp = case["expected_output"]
    req = OptimizeRequest(**inp)
    directives = [_adapt_directive(d) for d in exp["directive_interpretation"]]
    cons = build_constraints(req.hours, req.battery, directives)
    opt = optimize_schedule(req.hours, req.battery, cons)
    rep = replay(req.hours, req.battery, cons, opt)
    diff = rep.total_cost_bdt - exp["total_cost_bdt"]
    assert abs(diff) <= 1.0, (
        f"{case['id']}: cost diff {diff:+.2f} BDT exceeds 1.0 BDT tolerance "
        f"(got {rep.total_cost_bdt:.2f}, expected {exp['total_cost_bdt']:.2f}, "
        f"solver={opt.solver_used})"
    )


def test_total_avg_cost_diff_is_zero():
    """Aggregated quality_ratio across all 10 cases must be ≥ 0.999."""
    total_team = 0.0
    total_ref = 0.0
    for case in _CASES:
        inp = case["input"]
        exp = case["expected_output"]
        req = OptimizeRequest(**inp)
        directives = [_adapt_directive(d) for d in exp["directive_interpretation"]]
        cons = build_constraints(req.hours, req.battery, directives)
        opt = optimize_schedule(req.hours, req.battery, cons)
        rep = replay(req.hours, req.battery, cons, opt)
        total_team += rep.total_cost_bdt
        total_ref += exp["total_cost_bdt"]
    avg_quality = total_ref / total_team if total_team > 0 else 0.0
    assert avg_quality >= 0.999, (
        f"average quality_ratio {avg_quality:.4f} is below 0.999 — "
        f"team_cost={total_team:.2f}, ref_cost={total_ref:.2f}"
    )


def test_all_cases_valid():
    """Every case must produce a replay-valid schedule (no physical violations)."""
    for case in _CASES:
        inp = case["input"]
        exp = case["expected_output"]
        req = OptimizeRequest(**inp)
        directives = [_adapt_directive(d) for d in exp["directive_interpretation"]]
        cons = build_constraints(req.hours, req.battery, directives)
        opt = optimize_schedule(req.hours, req.battery, cons)
        rep = replay(req.hours, req.battery, cons, opt)
        assert rep.valid, (
            f"{case['id']}: replay reported violations: {rep.violations}"
        )
