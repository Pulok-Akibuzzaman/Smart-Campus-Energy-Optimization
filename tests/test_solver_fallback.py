"""
Defence-in-depth: assert scipy fallback works when PuLP is unavailable.

This addresses the bug discovered in Pulok's optimizer (HiGHS-not-available
exception handling: the try/except wrapped only the PuLP constructor, not
prob.solve(), so a missing highspy raised inside .solve() and 500'd the
endpoint). Ashik's optimizer.py calls PuLP first, scipy fallback second;
this test simulates PuLP being absent and verifies scipy takes over.

Run with:
    PYTHONPATH=src pytest tests/test_solver_fallback.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


def test_scipy_fallback_when_pulp_unavailable(monkeypatch):
    """If PuLP is unavailable, scipy fallback must succeed."""
    # Block pulp import inside the optimizer module.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pulp" or name.startswith("pulp."):
            raise ImportError("simulated pulp unavailability")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # Now construct a tiny problem and solve via scipy fallback.
    from gridwise.schemas import (
        BatterySpec,
        DirectiveInterpretationEntry,
        DirectiveType,
        HourEntry,
        NoChargeWindowAdjustment,
        OptimizeRequest,
    )
    from gridwise.constraints import build_constraints
    from gridwise.optimizer import optimize_schedule

    inp = {
        "scenario_id": "fallback-test",
        "operator_notes": ["do not charge from 1pm to 4pm"],
        "hours": [
            {
                "hour": h,
                "demand_kwh": 100.0 + (h % 5) * 5.0,
                "solar_kwh": max(0.0, 30.0 - abs(12 - h) * 3.0),
                "tariff_bdt_per_kwh": 8.0 + (h // 6) * 4.0,
            }
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 200.0,
            "initial_energy_kwh": 100.0,
            "minimum_energy_kwh": 30.0,
            "max_charge_kwh_per_hour": 50.0,
            "max_discharge_kwh_per_hour": 60.0,
        },
    }
    req = OptimizeRequest(**inp)
    directives = [
        DirectiveInterpretationEntry(
            note_index=0,
            applies=True,
            directive_type=DirectiveType.NO_CHARGE_WINDOW,
            structured_adjustment=NoChargeWindowAdjustment(hours=[13, 14, 15]),
            explanation="test directive",
        )
    ]
    cons = build_constraints(req.hours, req.battery, directives)
    result = optimize_schedule(req.hours, req.battery, cons)
    # Must use scipy because pulp was blocked.
    assert result.solver_used.startswith("scipy"), (
        f"expected scipy fallback when PuLP is unavailable, "
        f"got {result.solver_used!r}"
    )
    # And must produce an optimal schedule.
    assert result.status == "optimal"
    assert all(g >= 0.0 for g in result.grid), "grid_kwh must be non-negative"
    # no_charge_window must be respected
    assert all(c == 0.0 for c in [result.charge[13], result.charge[14], result.charge[15]])
