"""Defense-in-Depth Schedule Replay and Self-Validation.

Replays the 24-hour dispatch schedule hour-by-hour against all physical equations,
battery constraints, and active operator directives before returning the API response.
"""

from typing import List, Tuple
from app.schemas import (
    HourInput,
    BatteryInput,
    DirectiveInterpretationEntry,
    HourlyPlanEntry,
)


def replay_and_validate_schedule(
    hours: List[HourInput],
    battery: BatteryInput,
    directives: List[DirectiveInterpretationEntry],
    plan: List[HourlyPlanEntry],
    tolerance: float = 0.01
) -> Tuple[float, float, float, str]:
    """
    Independently replays and verifies the final schedule.

    Returns:
      recalculated (total_grid_kwh, total_cost_bdt, peak_grid_kwh, plan_summary)
    Raises:
      ValueError if any physical or directive constraint is violated beyond tolerance.
    """
    if len(plan) != 24:
        raise ValueError(f"Hourly plan must contain exactly 24 entries, found {len(plan)}")

    n_hours = 24
    effective_solar = [h.solar_kwh for h in hours]
    max_grid_limit = [float("inf")] * n_hours
    min_battery_reserve = [battery.minimum_energy_kwh] * n_hours
    allow_charge = [True] * n_hours
    allow_discharge = [True] * n_hours

    active_directives_count = 0
    noop_count = 0

    for d in directives:
        if not d.applies or not d.structured_adjustment:
            noop_count += 1
            continue

        active_directives_count += 1
        adj = d.structured_adjustment
        affected = adj.get("hours", [])

        if d.directive_type == "solar_reduction":
            factor = float(adj.get("factor", 1.0))
            for h in affected:
                if 0 <= h < n_hours:
                    effective_solar[h] = effective_solar[h] * factor

        elif d.directive_type == "minimum_battery_reserve":
            res_val = float(adj.get("minimum_energy_kwh", battery.minimum_energy_kwh))
            for h in affected:
                if 0 <= h < n_hours:
                    min_battery_reserve[h] = max(min_battery_reserve[h], res_val)

        elif d.directive_type == "no_charge_window":
            for h in affected:
                if 0 <= h < n_hours:
                    allow_charge[h] = False

        elif d.directive_type == "no_discharge_window":
            for h in affected:
                if 0 <= h < n_hours:
                    allow_discharge[h] = False

        elif d.directive_type == "max_grid_window":
            cap_val = float(adj.get("max_grid_kwh", float("inf")))
            for h in affected:
                if 0 <= h < n_hours:
                    max_grid_limit[h] = min(max_grid_limit[h], cap_val)

    # Replay simulation
    current_energy = battery.initial_energy_kwh
    total_grid_kwh = 0.0
    total_cost_bdt = 0.0
    peak_grid_kwh = 0.0

    for h in range(n_hours):
        entry = plan[h]
        if entry.hour != h:
            raise ValueError(f"Plan entry at index {h} has mismatched hour {entry.hour}")

        g = entry.grid_kwh
        s = entry.solar_used_kwh
        action = entry.battery_action
        bat_kwh = entry.battery_kwh
        e_after = entry.battery_energy_after_kwh

        # Non-negative checks
        if g < -tolerance or s < -tolerance or bat_kwh < -tolerance or e_after < -tolerance:
            raise ValueError(f"Hour {h}: negative energy value detected")

        # Solar constraint
        if s > effective_solar[h] + tolerance:
            raise ValueError(
                f"Hour {h}: solar_used_kwh ({s:.2f}) exceeds effective solar ({effective_solar[h]:.2f})"
            )

        # Battery action checks
        charge_kwh = bat_kwh if action == "charge" else 0.0
        discharge_kwh = bat_kwh if action == "discharge" else 0.0

        if action == "idle" and bat_kwh > tolerance:
            raise ValueError(f"Hour {h}: battery_action is idle but battery_kwh is {bat_kwh}")

        # Rate limits and window directives
        if not allow_charge[h] and charge_kwh > tolerance:
            raise ValueError(f"Hour {h}: charging during active no_charge_window")
        if not allow_discharge[h] and discharge_kwh > tolerance:
            raise ValueError(f"Hour {h}: discharging during active no_discharge_window")

        if charge_kwh > battery.max_charge_kwh_per_hour + tolerance:
            raise ValueError(f"Hour {h}: charge rate {charge_kwh:.2f} exceeds max {battery.max_charge_kwh_per_hour:.2f}")
        if discharge_kwh > battery.max_discharge_kwh_per_hour + tolerance:
            raise ValueError(f"Hour {h}: discharge rate {discharge_kwh:.2f} exceeds max {battery.max_discharge_kwh_per_hour:.2f}")

        # Grid cap directive
        if g > max_grid_limit[h] + tolerance:
            raise ValueError(f"Hour {h}: grid_kwh ({g:.2f}) exceeds max_grid limit ({max_grid_limit[h]:.2f})")

        # Energy balance
        # grid + solar_used + discharge = demand + charge
        left_side = g + s + discharge_kwh
        right_side = hours[h].demand_kwh + charge_kwh
        if abs(left_side - right_side) > tolerance:
            raise ValueError(
                f"Hour {h}: energy balance violation! Left={left_side:.2f} vs Right={right_side:.2f}"
            )

        # Battery state transition: E_after = E_before + charge - discharge
        expected_e_after = current_energy + charge_kwh - discharge_kwh
        if abs(e_after - expected_e_after) > tolerance:
            raise ValueError(
                f"Hour {h}: battery transition mismatch! Got {e_after:.2f}, expected {expected_e_after:.2f}"
            )

        # Battery bounds
        if e_after < min_battery_reserve[h] - tolerance:
            raise ValueError(
                f"Hour {h}: battery energy {e_after:.2f} below required reserve {min_battery_reserve[h]:.2f}"
            )
        if e_after > battery.capacity_kwh + tolerance:
            raise ValueError(
                f"Hour {h}: battery energy {e_after:.2f} exceeds capacity {battery.capacity_kwh:.2f}"
            )

        current_energy = e_after
        total_grid_kwh += g
        total_cost_bdt += g * hours[h].tariff_bdt_per_kwh
        if g > peak_grid_kwh:
            peak_grid_kwh = g

    # End-of-day neutrality check
    if abs(current_energy - battery.initial_energy_kwh) > tolerance:
        raise ValueError(
            f"End-of-day battery neutrality violation! Final energy {current_energy:.2f} != initial {battery.initial_energy_kwh:.2f}"
        )

    # Build human-readable plan summary
    plan_summary = (
        f"24-hour optimal dispatch generated successfully. "
        f"Processed {len(directives)} operator note(s): {active_directives_count} applied directive(s), "
        f"{noop_count} distractor(s) marked no_op. "
        f"Total grid electricity: {total_grid_kwh:.2f} kWh, "
        f"Peak grid demand: {peak_grid_kwh:.2f} kWh, "
        f"Total grid cost: {total_cost_bdt:.2f} BDT. "
        f"Strict energy balance, battery rate/reserve limits, and end-of-day neutrality verified."
    )

    return (
        round(total_grid_kwh, 2),
        round(total_cost_bdt, 2),
        round(peak_grid_kwh, 2),
        plan_summary
    )
