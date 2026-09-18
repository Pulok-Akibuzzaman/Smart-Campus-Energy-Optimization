"""
Replay-validate the optimizer's output and re-derive response totals.

Why this matters: the judge replays the schedule independently to verify
every applicable directive was actually applied. We do the same so that
any mismatch between what we report and what the judge recomputes is
caught here — never silently shipped.

Section 11.3 of the Problem Statement defines the canonical checks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple

from .constraints import HourlyConstraints
from .optimizer import OptimizerResult
from .schemas import BatterySpec, HourEntry, HourlyPlanEntry, BatteryAction

log = logging.getLogger(__name__)

# Tolerance per Section 11.5
TOL = 1e-2  # 0.01 kWh / 0.01 BDT


@dataclass
class ReplayReport:
    valid: bool
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    violations: List[str]


def _near(a: float, b: float, tol: float = TOL) -> bool:
    return abs(a - b) <= tol


def replay(
    hours: List[HourEntry],
    battery: BatterySpec,
    cons: HourlyConstraints,
    opt: OptimizerResult,
) -> ReplayReport:
    """Validate the optimizer's solution and re-derive response totals."""
    n = len(hours)
    violations: List[str] = []

    # 1) Non-negative + finite values
    for h in range(n):
        if opt.grid[h] < -TOL:
            violations.append(f"h{h}: negative grid {opt.grid[h]:.4f}")
        if opt.solar_used[h] < -TOL:
            violations.append(f"h{h}: negative solar {opt.solar_used[h]:.4f}")
        if opt.charge[h] < -TOL:
            violations.append(f"h{h}: negative charge {opt.charge[h]:.4f}")
        if opt.discharge[h] < -TOL:
            violations.append(f"h{h}: negative discharge {opt.discharge[h]:.4f}")

    # 2) Solar used <= effective_solar
    for h in range(n):
        if opt.solar_used[h] > cons.effective_solar[h] + TOL:
            violations.append(
                f"h{h}: solar_used {opt.solar_used[h]:.3f} > effective {cons.effective_solar[h]:.3f}"
            )

    # 3) Battery dynamics
    initial = float(battery.initial_energy_kwh)
    capacity = float(battery.capacity_kwh)
    max_ch = float(battery.max_charge_kwh_per_hour)
    max_dis = float(battery.max_discharge_kwh_per_hour)

    for h in range(n):
        e_before = initial if h == 0 else opt.energy_after[h - 1]
        expected = e_before + opt.charge[h] - opt.discharge[h]
        if not _near(opt.energy_after[h], expected):
            violations.append(
                f"h{h}: battery dynamics mismatch "
                f"({opt.energy_after[h]:.3f} vs {expected:.3f})"
            )

    # 4) Battery bounds (with raised minimum)
    for h in range(n):
        if opt.energy_after[h] < cons.min_battery_energy[h] - TOL:
            violations.append(
                f"h{h}: battery energy {opt.energy_after[h]:.3f} below min {cons.min_battery_energy[h]:.3f}"
            )
        if opt.energy_after[h] > capacity + TOL:
            violations.append(
                f"h{h}: battery energy {opt.energy_after[h]:.3f} above capacity {capacity:.3f}"
            )

    # 5) Charge / discharge rate limits
    for h in range(n):
        if opt.charge[h] > max_ch + TOL:
            violations.append(f"h{h}: charge {opt.charge[h]:.3f} > max {max_ch}")
        if opt.discharge[h] > max_dis + TOL:
            violations.append(f"h{h}: discharge {opt.discharge[h]:.3f} > max {max_dis}")

    # 6) no_charge_window / no_discharge_window
    for h in range(n):
        if cons.charge_forced_zero[h] and opt.charge[h] > TOL:
            violations.append(f"h{h}: charge during no_charge_window ({opt.charge[h]:.3f})")
        if cons.discharge_forced_zero[h] and opt.discharge[h] > TOL:
            violations.append(f"h{h}: discharge during no_discharge_window ({opt.discharge[h]:.3f})")

    # 7) Energy balance per hour
    for h in range(n):
        demand = float(hours[h].demand_kwh)
        lhs = opt.grid[h] + opt.solar_used[h] + opt.discharge[h]
        rhs = demand + opt.charge[h]
        if not _near(lhs, rhs):
            violations.append(
                f"h{h}: energy balance mismatch ({lhs:.3f} vs {rhs:.3f})"
            )

    # 8) max_grid_window
    for h in range(n):
        cap = cons.max_grid_kwh[h]
        if cap != float("inf") and opt.grid[h] > cap + TOL:
            violations.append(f"h{h}: grid {opt.grid[h]:.3f} exceeds cap {cap:.3f}")

    # 9) End-of-day neutrality
    if not _near(opt.energy_after[n - 1], initial):
        violations.append(
            f"end-of-day battery {opt.energy_after[n - 1]:.3f} != initial {initial:.3f}"
        )

    # Totals
    total_grid = sum(opt.grid)
    total_cost = sum(opt.grid[h] * float(hours[h].tariff_bdt_per_kwh) for h in range(n))
    peak_grid = max(opt.grid) if opt.grid else 0.0

    return ReplayReport(
        valid=len(violations) == 0,
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
        violations=violations,
    )


def build_hourly_plan(
    hours: List[HourEntry],
    opt: OptimizerResult,
) -> List[HourlyPlanEntry]:
    """Convert optimizer output to the public HourlyPlanEntry schema.

    Rounding to 4 decimals keeps the response clean while staying well below
    the 0.01 tolerance band.
    """
    plan: List[HourlyPlanEntry] = []
    for h in range(len(hours)):
        ch = opt.charge[h]
        dis = opt.discharge[h]
        if ch > TOL and dis > TOL:
            # Should never happen — solver enforces one direction.
            if ch >= dis:
                action = BatteryAction.CHARGE
                battery_kwh = ch
            else:
                action = BatteryAction.DISCHARGE
                battery_kwh = dis
        elif ch > TOL:
            action = BatteryAction.CHARGE
            battery_kwh = ch
        elif dis > TOL:
            action = BatteryAction.DISCHARGE
            battery_kwh = dis
        else:
            action = BatteryAction.IDLE
            battery_kwh = 0.0

        plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(max(0.0, opt.grid[h]), 4),
                solar_used_kwh=round(max(0.0, opt.solar_used[h]), 4),
                battery_action=action,
                battery_kwh=round(max(0.0, battery_kwh), 4),
                battery_energy_after_kwh=round(max(0.0, opt.energy_after[h]), 4),
            )
        )
    return plan
