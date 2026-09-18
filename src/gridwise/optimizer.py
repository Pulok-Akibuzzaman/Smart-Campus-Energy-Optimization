"""
Linear-program optimizer for the 24-hour GridWise schedule.

Primary solver: PuLP with the bundled CBC solver.
Fallback solver: scipy.optimize.linprog (HiGHS).

Decision variables per hour h ∈ [0..23]:
  grid[h]        >= 0   (grid_kwh)
  solar[h]       >= 0   (solar_used_kwh)
  charge[h]      >= 0   (battery_charge_kwh)
  discharge[h]   >= 0   (battery_discharge_kwh)
  E[h]           free   (battery_energy_after_kwh)

Objective:
  minimize Σ_h grid[h] * tariff[h]

Constraints (per h):
  energy balance:  grid + solar + discharge == demand + charge
  solar usage:     solar <= effective_solar[h]
  battery bound:   min_battery_energy[h] <= E[h] <= capacity
  charge limit:    charge <= max_charge_per_hour; charge == 0 in no_charge_window
  discharge limit: discharge <= max_discharge_per_hour; discharge == 0 in no_discharge_window
  dynamics:        E[h] == E[h-1] + charge[h] - discharge[h],  E[0] == initial_energy
  grid cap:        grid <= max_grid_kwh[h]   (if finite)
  end-of-day:      E[23] == initial_energy
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from .constraints import HourlyConstraints
from .schemas import BatterySpec, HourEntry

log = logging.getLogger(__name__)

# Tiny epsilon to keep HiGHS / CBC away from the boundary when a cap == 0
# would otherwise force grid_kwh == 0 exactly. We tolerate this.
_EPS = 1e-9


@dataclass
class OptimizerResult:
    grid: List[float]
    solar_used: List[float]
    charge: List[float]
    discharge: List[float]
    energy_after: List[float]
    objective_value: float
    solver_used: str
    status: str


# ─────────────────────────── PuLP primary ───────────────────────────


def _solve_with_pulp(
    hours: List[HourEntry],
    battery: BatterySpec,
    cons: HourlyConstraints,
) -> Optional[OptimizerResult]:
    """Try to solve with PuLP. Returns None if PuLP is unavailable or solver fails."""
    try:
        import pulp  # type: ignore
    except Exception as e:  # pragma: no cover - import guard
        log.warning("PuLP not available: %s", e)
        return None

    n = len(hours)
    prob = pulp.LpProblem("gridwise", pulp.LpMinimize)

    # Variables
    grid = [pulp.LpVariable(f"grid_{h}", lowBound=0) for h in range(n)]
    solar = [pulp.LpVariable(f"solar_{h}", lowBound=0) for h in range(n)]
    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0) for h in range(n)]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0) for h in range(n)]
    E = [pulp.LpVariable(f"E_{h}", lowBound=0) for h in range(n)]

    # Objective: minimize Σ grid[h] * tariff[h]
    prob += pulp.lpSum(
        grid[h] * float(hours[h].tariff_bdt_per_kwh) for h in range(n)
    )

    capacity = float(battery.capacity_kwh)
    initial = float(battery.initial_energy_kwh)
    max_ch = float(battery.max_charge_kwh_per_hour)
    max_dis = float(battery.max_discharge_kwh_per_hour)

    for h in range(n):
        demand = float(hours[h].demand_kwh)
        eff_solar = float(cons.effective_solar[h])
        min_e = float(cons.min_battery_energy[h])

        # Battery bounds
        prob += E[h] <= capacity, f"cap_{h}"
        prob += E[h] >= min_e, f"minE_{h}"

        # Solar cap
        prob += solar[h] <= eff_solar + _EPS, f"solarcap_{h}"

        # Charge rate
        prob += charge[h] <= max_ch + _EPS, f"chrate_{h}"
        if cons.charge_forced_zero[h]:
            prob += charge[h] == 0, f"noch_{h}"

        # Discharge rate
        prob += discharge[h] <= max_dis + _EPS, f"disrate_{h}"
        if cons.discharge_forced_zero[h]:
            prob += discharge[h] == 0, f"nodis_{h}"

        # Grid cap (if finite)
        if cons.max_grid_kwh[h] != float("inf"):
            prob += grid[h] <= float(cons.max_grid_kwh[h]) + _EPS, f"gridcap_{h}"

        # Dynamics: E[h] == E_before + charge[h] - discharge[h].
        # At h=0 the previous state IS the initial energy (charge/discharge in
        # hour 0 still move from that initial).
        e_before = initial if h == 0 else E[h - 1]
        prob += E[h] == e_before + charge[h] - discharge[h], f"dyn_{h}"

        # Energy balance
        prob += (
            grid[h] + solar[h] + discharge[h] == demand + charge[h]
        ), f"bal_{h}"

    # End-of-day neutrality (already implied by dynamics + the initial binding
    # of E[0] == initial, but we keep an explicit equality so the LP never
    # accidentally closes at a different SoC due to numerical noise).
    prob += E[n - 1] == initial, "E_eod"

    # Initial state binding (independent of dynamics so it acts as a hard anchor).
    prob += E[0] == initial, "E_init"

    # Solve (CBC, silent)
    solver = pulp.PULP_CBC_CMD(msg=False)
    try:
        status = prob.solve(solver)
    except Exception as e:  # pragma: no cover - solver failure
        log.warning("PuLP solve raised: %s", e)
        return None

    if pulp.LpStatus[status] not in ("Optimal", "Not Solved"):
        log.warning("PuLP non-optimal status: %s", pulp.LpStatus[status])

    # Extract solution. If infeasible we get None values.
    try:
        grid_vals = [float(grid[h].value() or 0.0) for h in range(n)]
        solar_vals = [float(solar[h].value() or 0.0) for h in range(n)]
        charge_vals = [float(charge[h].value() or 0.0) for h in range(n)]
        discharge_vals = [float(discharge[h].value() or 0.0) for h in range(n)]
        E_vals = [float(E[h].value() or 0.0) for h in range(n)]
        obj = float(pulp.value(prob.objective) or 0.0)
    except Exception as e:  # pragma: no cover
        log.warning("PuLP extract failed: %s", e)
        return None

    return OptimizerResult(
        grid=grid_vals,
        solar_used=solar_vals,
        charge=charge_vals,
        discharge=discharge_vals,
        energy_after=E_vals,
        objective_value=obj,
        solver_used="pulp",
        status=pulp.LpStatus[status],
    )


# ─────────────────────── scipy linprog fallback ─────────────────────


def _solve_with_scipy(
    hours: List[HourEntry],
    battery: BatterySpec,
    cons: HourlyConstraints,
) -> Optional[OptimizerResult]:
    """Fallback LP via scipy linprog (HiGHS).

    Variables are flattened to a single vector:
      [grid_0..23, solar_0..23, charge_0..23, discharge_0..23, E_0..23]
    """
    try:
        import numpy as np  # type: ignore
        from scipy.optimize import linprog  # type: ignore
    except Exception as e:  # pragma: no cover - import guard
        log.warning("scipy/numpy not available: %s", e)
        return None

    n = len(hours)
    nv = n * 5  # grid, solar, charge, discharge, E

    # Index helpers
    def idx(kind: str, h: int) -> int:
        offsets = {"grid": 0, "solar": n, "charge": 2 * n, "discharge": 3 * n, "E": 4 * n}
        return offsets[kind] + h

    # Objective: minimize Σ grid[h] * tariff[h]
    c = np.zeros(nv)
    for h in range(n):
        c[idx("grid", h)] = float(hours[h].tariff_bdt_per_kwh)

    capacity = float(battery.capacity_kwh)
    initial = float(battery.initial_energy_kwh)
    max_ch = float(battery.max_charge_kwh_per_hour)
    max_dis = float(battery.max_discharge_kwh_per_hour)

    # Build equality constraints: balance per h, dynamics per h>0, E0=init, Eeod=init.
    A_eq_rows: List[List[float]] = []
    b_eq: List[float] = []
    for h in range(n):
        demand = float(hours[h].demand_kwh)
        # Energy balance: grid + solar + discharge - charge == demand
        row = [0.0] * nv
        row[idx("grid", h)] = 1.0
        row[idx("solar", h)] = 1.0
        row[idx("discharge", h)] = 1.0
        row[idx("charge", h)] = -1.0
        A_eq_rows.append(row)
        b_eq.append(demand)

    for h in range(1, n):
        # E[h] - E[h-1] - charge[h] + discharge[h] == 0
        row = [0.0] * nv
        row[idx("E", h)] = 1.0
        row[idx("E", h - 1)] = -1.0
        row[idx("charge", h)] = -1.0
        row[idx("discharge", h)] = 1.0
        A_eq_rows.append(row)
        b_eq.append(0.0)

    # E0 == initial
    row = [0.0] * nv
    row[idx("E", 0)] = 1.0
    A_eq_rows.append(row)
    b_eq.append(initial)

    # E[n-1] == initial  (end-of-day neutrality)
    row = [0.0] * nv
    row[idx("E", n - 1)] = 1.0
    A_eq_rows.append(row)
    b_eq.append(initial)

    A_eq = np.array(A_eq_rows)
    b_eq_arr = np.array(b_eq)

    # Bounds
    bounds: List[tuple] = []
    for h in range(n):
        # grid
        upper = float(cons.max_grid_kwh[h]) if cons.max_grid_kwh[h] != float("inf") else None
        bounds.append((0, upper))
    for h in range(n):
        bounds.append((0, float(cons.effective_solar[h])))  # solar
    for h in range(n):
        upper = 0.0 if cons.charge_forced_zero[h] else max_ch
        bounds.append((0, upper))
    for h in range(n):
        upper = 0.0 if cons.discharge_forced_zero[h] else max_dis
        bounds.append((0, upper))
    for h in range(n):
        lo = float(cons.min_battery_energy[h])
        bounds.append((lo, capacity))

    try:
        res = linprog(
            c=c,
            A_eq=A_eq,
            b_eq=b_eq_arr,
            bounds=bounds,
            method="highs",
        )
    except Exception as e:  # pragma: no cover
        log.warning("scipy linprog raised: %s", e)
        return None

    if not res.success or res.x is None:
        log.warning("scipy linprog failed: %s", res.message)
        return None

    x = res.x
    return OptimizerResult(
        grid=[float(x[idx("grid", h)]) for h in range(n)],
        solar_used=[float(x[idx("solar", h)]) for h in range(n)],
        charge=[float(x[idx("charge", h)]) for h in range(n)],
        discharge=[float(x[idx("discharge", h)]) for h in range(n)],
        energy_after=[float(x[idx("E", h)]) for h in range(n)],
        objective_value=float(res.fun),
        solver_used="scipy",
        status="optimal",
    )


# ─────────────────────────── Public entrypoint ───────────────────────


def optimize_schedule(
    hours: List[HourEntry],
    battery: BatterySpec,
    cons: HourlyConstraints,
) -> OptimizerResult:
    """Solve the LP. PuLP first, scipy fallback, raises RuntimeError if both fail."""
    result = _solve_with_pulp(hours, battery, cons)
    if result is not None:
        return result
    log.warning("Falling back to scipy linprog")
    result = _solve_with_scipy(hours, battery, cons)
    if result is not None:
        return result
    raise RuntimeError("No LP solver available: PuLP and scipy linprog both failed")
