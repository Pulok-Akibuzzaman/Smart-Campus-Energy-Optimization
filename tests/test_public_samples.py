"""
End-to-end test harness for the public GridWise sample cases.

This test runs the *deterministic* portion of the pipeline (validator →
constraints → optimizer → replay) against the public sample cases. The LLM
interpretation layer is bypassed by feeding the EXPECTED directive
interpretation directly into the validator — this isolates and tests the
math/optimization correctness independently of LLM provider availability.

When run, this script:
  1) Loads BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json
  2) For each case, builds an OptimizeRequest + Directive list
  3) Runs optimize_schedule + replay
  4) Compares totals against the reference expected_output
  5) Prints a summary table
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure src/ is importable when run from project root
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gridwise.constraints import build_constraints  # noqa: E402
from gridwise.optimizer import optimize_schedule  # noqa: E402
from gridwise.replay import replay  # noqa: E402
from gridwise.schemas import (  # noqa: E402
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
from gridwise.validator import validate_all  # noqa: E402

SAMPLES_PATH = PROJECT_ROOT.parent / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

ADJ_PARSERS = {
    "solar_reduction": lambda a: SolarReductionAdjustment(
        hours=a["hours"], factor=float(a["factor"])
    ),
    "minimum_battery_reserve": lambda a: MinimumBatteryReserveAdjustment(
        hours=a["hours"], minimum_energy_kwh=float(a["minimum_energy_kwh"])
    ),
    "no_charge_window": lambda a: NoChargeWindowAdjustment(hours=a["hours"]),
    "no_discharge_window": lambda a: NoDischargeWindowAdjustment(hours=a["hours"]),
    "max_grid_window": lambda a: MaxGridWindowAdjustment(
        hours=a["hours"], max_grid_kwh=float(a["max_grid_kwh"])
    ),
}


def _load_samples() -> List[Dict[str, Any]]:
    with SAMPLES_PATH.open() as f:
        return json.load(f)["cases"]


def _entry_from_expected(raw: Dict[str, Any]) -> DirectiveInterpretationEntry:
    d_type = raw["directive_type"]
    if d_type == "no_op":
        return DirectiveInterpretationEntry(
            note_index=raw["note_index"],
            applies=False,
            directive_type=DirectiveType.NO_OP,
            structured_adjustment=None,
            explanation=raw.get("explanation", "no_op"),
        )
    adj_dict = raw.get("structured_adjustment") or {}
    parser = ADJ_PARSERS[d_type]
    return DirectiveInterpretationEntry(
        note_index=raw["note_index"],
        applies=True,
        directive_type=DirectiveType(d_type),
        structured_adjustment=parser(adj_dict),
        explanation=raw.get("explanation", d_type),
    )


def run_case(case: Dict[str, Any]) -> Tuple[bool, str, Dict[str, float]]:
    """Returns (ok, status_message, totals_dict)."""
    inp = case["input"]
    expected = case["expected_output"]

    # Build typed objects.
    hours = [
        HourEntry(
            hour=h["hour"],
            demand_kwh=h["demand_kwh"],
            solar_kwh=h["solar_kwh"],
            tariff_bdt_per_kwh=h["tariff_bdt_per_kwh"],
        )
        for h in inp["hours"]
    ]
    battery = BatterySpec(**inp["battery"])

    # Use the EXPECTED directive list (we're testing the optimizer, not the LLM).
    directives = [_entry_from_expected(d) for d in expected["directive_interpretation"]]

    # Run the math pipeline.
    cons = build_constraints(hours, battery, directives)
    try:
        opt = optimize_schedule(hours, battery, cons)
    except Exception as e:
        return False, f"optimize failed: {e}", {}

    report = replay(hours, battery, cons, opt)

    # Compare totals to reference.
    exp_grid = float(expected["total_grid_kwh"])
    exp_cost = float(expected["total_cost_bdt"])
    exp_peak = float(expected["peak_grid_kwh"])

    grid_diff = report.total_grid_kwh - exp_grid
    cost_diff = report.total_cost_bdt - exp_cost
    peak_diff = report.peak_grid_kwh - exp_peak

    msg = (
        f"valid={report.valid} "
        f"grid={report.total_grid_kwh:.2f} (exp {exp_grid:.2f}, Δ {grid_diff:+.2f}) "
        f"cost={report.total_cost_bdt:.2f} (exp {exp_cost:.2f}, Δ {cost_diff:+.2f}) "
        f"peak={report.peak_grid_kwh:.2f} (exp {exp_peak:.2f}, Δ {peak_diff:+.2f}) "
        f"solver={opt.solver_used}"
    )
    if report.violations:
        msg += f" violations={report.violations[:3]}"
    return report.valid, msg, {
        "grid": report.total_grid_kwh,
        "cost": report.total_cost_bdt,
        "peak": report.peak_grid_kwh,
        "exp_grid": exp_grid,
        "exp_cost": exp_cost,
        "exp_peak": exp_peak,
    }


def main() -> int:
    cases = _load_samples()
    print(f"Loaded {len(cases)} public sample cases from {SAMPLES_PATH.name}\n")
    ok_count = 0
    total_cost_ratio = 0.0
    quality_count = 0

    for case in cases:
        cid = case["id"]
        label = case.get("label", "")
        ok, msg, totals = run_case(case)
        marker = "OK " if ok else "FAIL"
        print(f"[{marker}] {cid}  {label}")
        print(f"       {msg}")
        if ok:
            ok_count += 1
        if totals:
            org_cost = totals["exp_cost"]
            team_cost = totals["cost"]
            if org_cost > 0.01:
                ratio = min(1.0, org_cost / team_cost) if team_cost > 0.01 else 0.0
                total_cost_ratio += ratio
                quality_count += 1
        print()

    print(f"Summary: {ok_count}/{len(cases)} cases valid (math only)")
    if quality_count:
        print(
            f"         avg quality_ratio (org_cost / team_cost): "
            f"{total_cost_ratio / quality_count:.3f}"
        )
    return 0 if ok_count == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
