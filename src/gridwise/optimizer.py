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

Lexicographic tie-breaker (so multiple optima collapse to one reproducible
plan and the cost diff vs reference is always 0):
  Stage 1: minimize Σ grid[h] * tariff[h]  -> c*
  Stage 2: add Σ grid[h] * tariff[h] == c* and minimize peak_grid,
           then total_grid, then lexicographic hour-by-hour grid[h].

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


def _build_pulp_constraints(
    prob,
    hours: List[HourEntry],
    battery: BatterySpec,
    cons: HourlyConstraints,
    grid,
    solar,
    charge,
    discharge,
    E,
    n: int,
    capacity: float,
    initial: float,
    max_ch: float,
    max_dis: float,
) -> None:
    """Attach all hard constraints (energy balance, dynamics, bounds, caps)
    to the given PuLP problem. Does NOT set the objective."""
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

        # Dynamics
        e_before = initial if h == 0 else E[h - 1]
        prob += E[h] == e_before + charge[h] - discharge[h], f"dyn_{h}"

        # Energy balance
        prob += (
            grid[h] + solar[h] + discharge[h] == demand + charge[h]
        ), f"bal_{h}"

    # End-of-day neutrality + initial binding
    prob += E[n - 1] == initial, "E_eod"
    prob += E[0] == initial, "E_init"


def _solve_with_pulp(
    hours: List[HourEntry],
    battery: BatterySpec,
    cons: HourlyConstraints,
) -> Optional[OptimizerResult]:
    """Solve with PuLP using a 2-stage lexicographic objective.

    Stage 1: minimize Σ grid[h] * tariff[h]  -> c*
    Stage 2: Σ grid[h] * tariff[h] == c*, minimize peak then total then
             lexicographic hour-by-hour grid[h].

    Returns None if PuLP is unavailable or solver fails.
    """
    try:
        import pulp  # type: ignore
    except Exception as e:  # pragma: no cover - import guard
        log.warning("PuLP not available: %s", e)
        return None

    n = len(hours)
    capacity = float(battery.capacity_kwh)
    initial = float(battery.initial_energy_kwh)
    max_ch = float(battery.max_charge_kwh_per_hour)
    max_dis = float(battery.max_discharge_kwh_per_hour)

    solver = pulp.PULP_CBC_CMD(msg=False)

    # ---------- Stage 1: minimize cost ----------
    prob1 = pulp.LpProblem("gridwise_stage1", pulp.LpMinimize)
    grid1 = [pulp.LpVariable(f"grid1_{h}", lowBound=0) for h in range(n)]
    solar1 = [pulp.LpVariable(f"solar1_{h}", lowBound=0) for h in range(n)]
    ch1 = [pulp.LpVariable(f"ch1_{h}", lowBound=0) for h in range(n)]
    dis1 = [pulp.LpVariable(f"dis1_{h}", lowBound=0) for h in range(n)]
    E1 = [pulp.LpVariable(f"E1_{h}", lowBound=0) for h in range(n)]
    _build_pulp_constraints(
        prob1, hours, battery, cons,
        grid1, solar1, ch1, dis1, E1,
        n, capacity, initial, max_ch, max_dis,
    )
    prob1 += pulp.lpSum(
        grid1[h] * float(hours[h].tariff_bdt_per_kwh) for h in range(n)
    ), "obj_cost"
    try:
        status1 = prob1.solve(solver)
    except Exception as e:
        log.warning("PuLP stage1 raised: %s", e)
        return None
    if pulp.LpStatus[status1] != "Optimal":
        log.warning("PuLP stage1 non-optimal: %s", pulp.LpStatus[status1])
        return None
    try:
        c_star = float(pulp.value(prob1.objective) or 0.0)
    except Exception:
        return None

    # ---------- Stage 2: tie-break ----------
    # Objective is the weighted sum of:
    #   peak_grid    weight = PEAK_W (largest; we minimize peak first)
    #   total_grid   weight = TOTAL_W (next)
    #   lexicographic hour weights: 1.0, 0.99, 0.99^2, ... for h=0..23
    #     so that minimizing grid[0] dominates grid[1] dominates grid[2] ...
    # We need all three to be positive and the peak weight to dominate total,
    # and total to dominate the lexicographic sum. Using PEAK_W=1e6, TOTAL_W=1e3
    # and lex weights < 1 keeps the ordering strictly correct in practice.
    PEAK_W = 1e6
    TOTAL_W = 1e3
    prob2 = pulp.LpProblem("gridwise_stage2", pulp.LpMinimize)
    grid = [pulp.LpVariable(f"grid_{h}", lowBound=0) for h in range(n)]
    solar = [pulp.LpVariable(f"solar_{h}", lowBound=0) for h in range(n)]
    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0) for h in range(n)]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0) for h in range(n)]
    E = [pulp.LpVariable(f"E_{h}", lowBound=0) for h in range(n)]
    _build_pulp_constraints(
        prob2, hours, battery, cons,
        grid, solar, charge, discharge, E,
        n, capacity, initial, max_ch, max_dis,
    )
    # Pin cost to c*
    prob2 += (
        pulp.lpSum(grid[h] * float(hours[h].tariff_bdt_per_kwh) for h in range(n))
        == c_star
    ), "pin_cost"

    peak = pulp.LpVariable("peak_grid", lowBound=0)
    for h in range(n):
        prob2 += peak >= grid[h], f"peak_{h}"
    total_grid = pulp.lpSum(grid[h] for h in range(n))
    lex_obj = pulp.lpSum(grid[h] * (0.99 ** h) for h in range(n))
    prob2 += PEAK_W * peak + TOTAL_W * total_grid + lex_obj, "obj_tie"

    try:
        status2 = prob2.solve(solver)
    except Exception as e:
        log.warning("PuLP stage2 raised: %s", e)
        return None
    if pulp.LpStatus[status2] != "Optimal":
        log.warning("PuLP stage2 non-optimal: %s", pulp.LpStatus[status2])
        return None

    try:
        grid_vals = [float(grid[h].value() or 0.0) for h in range(n)]
        solar_vals = [float(solar[h].value() or 0.0) for h in range(n)]
        charge_vals = [float(charge[h].value() or 0.0) for h in range(n)]
        discharge_vals = [float(discharge[h].value() or 0.0) for h in range(n)]
        E_vals = [float(E[h].value() or 0.0) for h in range(n)]
    except Exception as e:
        log.warning("PuLP extract failed: %s", e)
        return None

    return OptimizerResult(
        grid=grid_vals,
        solar_used=solar_vals,
        charge=charge_vals,
        discharge=discharge_vals,
        energy_after=E_vals,
        objective_value=c_star,
        solver_used="pulp",
        status="optimal",
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

    # ---------- Stage 1: minimum cost ----------
    try:
        res1 = linprog(
            c=c,
            A_eq=A_eq,
            b_eq=b_eq_arr,
            bounds=bounds,
            method="highs",
        )
    except Exception as e:  # pragma: no cover
        log.warning("scipy stage1 raised: %s", e)
        return None
    if not res1.success or res1.x is None:
        log.warning("scipy stage1 failed: %s", res1.message)
        return None
    c_star = float(res1.fun)

    # ---------- Stage 2: tie-break with weighted single objective ----------
    # Objective: minimize  PEAK_W*peak + TOTAL_W*Σ grid[h] + Σ grid[h]*0.99^h
    # Subject to: stage-1 cost == c_star
    # We introduce peak as a free variable with constraints peak >= grid[h].
    # Variable layout: grid_0..n, solar_0..n, charge_0..n, discharge_0..n,
    # E_0..n, peak
    nv2 = nv + 1
    peak_idx = nv

    c2 = np.zeros(nv2)
    PEAK_W = 1e6
    TOTAL_W = 1e3
    c2[peak_idx] = PEAK_W
    for h in range(n):
        c2[idx("grid", h)] = TOTAL_W + (0.99 ** h)

    # Equality: stage-1 cost == c_star
    cost_row = np.zeros(nv2)
    for h in range(n):
        cost_row[idx("grid", h)] = float(hours[h].tariff_bdt_per_kwh)
    A_eq2 = np.vstack([A_eq, cost_row.reshape(1, -1)])
    b_eq2 = np.concatenate([b_eq_arr, [c_star]])

    # Inequality: peak - grid[h] >= 0  for each h
    A_ub_rows = []
    b_ub = []
    for h in range(n):
        row = np.zeros(nv2)
        row[peak_idx] = 1.0
        row[idx("grid", h)] = -1.0
        A_ub_rows.append(row)
        b_ub.append(0.0)
    A_ub = np.array(A_ub_rows)

    bounds2 = list(bounds) + [(0.0, None)]  # peak lower 0

    try:
        res2 = linprog(
            c=c2,
            A_eq=A_eq2,
            b_eq=b_eq2,
            A_ub=A_ub,
            b_ub=np.array(b_ub),
            bounds=bounds2,
            method="highs",
        )
    except Exception as e:  # pragma: no cover
        log.warning("scipy stage2 raised: %s", e)
        return None
    if not res2.success or res2.x is None:
        log.warning("scipy stage2 failed: %s", res2.message)
        return None

    x = res2.x
    return OptimizerResult(
        grid=[float(x[idx("grid", h)]) for h in range(n)],
        solar_used=[float(x[idx("solar", h)]) for h in range(n)],
        charge=[float(x[idx("charge", h)]) for h in range(n)],
        discharge=[float(x[idx("discharge", h)]) for h in range(n)],
        energy_after=[float(x[idx("E", h)]) for h in range(n)],
        objective_value=c_star,
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
