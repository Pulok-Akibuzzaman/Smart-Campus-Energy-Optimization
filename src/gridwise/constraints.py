"""
Translate guardrailed operator-note directives into per-hour constraint arrays
consumed by the optimizer. Deterministic, side-effect-free.

Per Section 5.3 of the Problem Statement:
  solar_reduction          -> effective_solar[h] = original_solar[h] * factor
  minimum_battery_reserve  -> min_energy[h] = max(base, directive.min)
  no_charge_window         -> charge[h] = 0
  no_discharge_window      -> discharge[h] = 0
  max_grid_window          -> grid_max[h] = directive.max_grid_kwh
  no_op                    -> no constraint changes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .schemas import (
    DirectiveInterpretationEntry,
    HourEntry,
    BatterySpec,
)


@dataclass
class HourlyConstraints:
    """Per-hour bounds derived from base data + active directives."""

    # Effective usable solar (kWh) per hour — already reduced for solar_reduction.
    effective_solar: List[float]

    # Per-hour minimum battery energy after the hour (kWh). Base minimum,
    # raised by minimum_battery_reserve directives.
    min_battery_energy: List[float]

    # Hard upper bound on grid_kwh per hour. +inf unless a max_grid_window applies.
    max_grid_kwh: List[float]

    # Force charge to 0 in these hours (no_charge_window).
    charge_forced_zero: List[bool]

    # Force discharge to 0 in these hours (no_discharge_window).
    discharge_forced_zero: List[bool]

    # Human-readable summary of which directives changed what.
    applied_summary: List[str] = field(default_factory=list)


def build_constraints(
    hours: List[HourEntry],
    battery: BatterySpec,
    directives: List[DirectiveInterpretationEntry],
) -> HourlyConstraints:
    """Compute per-hour constraint arrays from base data + guardrailed directives.

    Invalid `hours` lists inside directives (duplicates, out of range) are
    silently dropped — they should have been caught by the guardrail validator
    upstream. Defense in depth.
    """

    n = len(hours)
    assert n == 24, "hours must have exactly 24 entries"

    effective_solar = [float(h.solar_kwh) for h in hours]
    min_battery = [float(battery.minimum_energy_kwh)] * n
    max_grid = [float("inf")] * n
    charge_zero = [False] * n
    discharge_zero = [False] * n
    summary: List[str] = []

    def _clean_hours(raw_hours) -> List[int]:
        """Deduplicate, sort ascending, clip to 0..23."""
        seen = set()
        out = []
        for h in raw_hours or []:
            try:
                hi = int(h)
            except (TypeError, ValueError):
                continue
            if hi < 0 or hi > 23 or hi in seen:
                continue
            seen.add(hi)
            out.append(hi)
        out.sort()
        return out

    for entry in directives:
        if not entry.applies:
            continue
        adj = entry.structured_adjustment
        if adj is None:
            continue

        d_type = entry.directive_type.value if hasattr(entry.directive_type, "value") else entry.directive_type

        if d_type == "solar_reduction":
            hrs = _clean_hours(getattr(adj, "hours", []))
            factor = float(getattr(adj, "factor", 1.0))
            factor = max(0.0, min(1.0, factor))
            for h in hrs:
                effective_solar[h] *= factor
            summary.append(
                f"solar_reduction: factor={factor:.2f} hours={hrs}"
            )

        elif d_type == "minimum_battery_reserve":
            hrs = _clean_hours(getattr(adj, "hours", []))
            target = float(getattr(adj, "minimum_energy_kwh", 0.0))
            for h in hrs:
                if target > min_battery[h]:
                    min_battery[h] = target
            summary.append(
                f"minimum_battery_reserve: {target:.2f} kWh hours={hrs}"
            )

        elif d_type == "no_charge_window":
            hrs = _clean_hours(getattr(adj, "hours", []))
            for h in hrs:
                charge_zero[h] = True
            summary.append(f"no_charge_window: hours={hrs}")

        elif d_type == "no_discharge_window":
            hrs = _clean_hours(getattr(adj, "hours", []))
            for h in hrs:
                discharge_zero[h] = True
            summary.append(f"no_discharge_window: hours={hrs}")

        elif d_type == "max_grid_window":
            hrs = _clean_hours(getattr(adj, "hours", []))
            cap = float(getattr(adj, "max_grid_kwh", 0.0))
            for h in hrs:
                # If multiple max_grid_window directives overlap, take the tighter cap.
                if cap < max_grid[h]:
                    max_grid[h] = cap
            summary.append(f"max_grid_window: cap={cap:.2f} kWh hours={hrs}")

        # no_op is silently ignored (already filtered by `applies`).

    return HourlyConstraints(
        effective_solar=effective_solar,
        min_battery_energy=min_battery,
        max_grid_kwh=max_grid,
        charge_forced_zero=charge_zero,
        discharge_forced_zero=discharge_zero,
        applied_summary=summary,
    )
