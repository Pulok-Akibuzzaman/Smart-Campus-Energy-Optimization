"""
Pydantic schemas matching the BUP CSE Fest 2026 Preliminary Problem Statement
sections 07 (request) and 10 (response).

Field names are kept verbatim from the spec so judge parsing works without
renaming. Unknown fields in incoming requests are ignored to stay lenient.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ──────────── Enums (Section 04) ────────────


class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class BatteryAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


# ──────────── Request schema (Section 07) ────────────


class HourEntry(BaseModel):
    """One of the 24 hourly entries in a scenario."""

    model_config = ConfigDict(extra="ignore")

    hour: int = Field(..., ge=0, le=23, description="Integer hour 0–23")
    demand_kwh: float = Field(..., ge=0, description="Campus demand in kWh")
    solar_kwh: float = Field(..., ge=0, description="Base solar available in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Grid tariff in BDT/kWh")

    @field_validator("demand_kwh", "solar_kwh", "tariff_bdt_per_kwh")
    @classmethod
    def _finite_non_negative(cls, v: float) -> float:
        # Spec requires finite, non-negative numeric values.
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("must be finite")
        return v


class BatterySpec(BaseModel):
    """Battery parameters (Section 07.3)."""

    model_config = ConfigDict(extra="ignore")

    capacity_kwh: float = Field(..., gt=0)
    initial_energy_kwh: float = Field(..., ge=0)
    minimum_energy_kwh: float = Field(..., ge=0)
    max_charge_kwh_per_hour: float = Field(..., gt=0)
    max_discharge_kwh_per_hour: float = Field(..., gt=0)

    @field_validator("initial_energy_kwh", "minimum_energy_kwh")
    @classmethod
    def _within_capacity(cls, v: float, info) -> float:
        # Cross-field check: initial/minimum cannot exceed capacity. We can't
        # access `capacity_kwh` here directly because it's declared after these,
        # so this is a sanity check for non-negativity + finite; the full
        # cross-field check is in OptimizeRequest._battery_consistent.
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("must be finite")
        return v


class OptimizeRequest(BaseModel):
    """Top-level request body for POST /optimize-energy (Section 07)."""

    model_config = ConfigDict(extra="ignore")

    scenario_id: str = Field(..., min_length=1)
    operator_notes: List[str] = Field(..., min_length=1, max_length=3)
    hours: List[HourEntry] = Field(..., min_length=24, max_length=24)
    battery: BatterySpec

    @field_validator("operator_notes")
    @classmethod
    def _non_empty_notes(cls, v: List[str]) -> List[str]:
        for i, note in enumerate(v):
            if not isinstance(note, str) or not note.strip():
                raise ValueError(f"operator_notes[{i}] must be a non-empty string")
        return v

    @field_validator("hours")
    @classmethod
    def _unique_hours_ascending(cls, v: List[HourEntry]) -> List[HourEntry]:
        hour_ids = [h.hour for h in v]
        if sorted(set(hour_ids)) != list(range(24)):
            raise ValueError(
                "hours must contain exactly unique integers 0..23 in ascending order"
            )
        # Already validated as 24 entries with the right hour ids.
        v_sorted = sorted(v, key=lambda h: h.hour)
        return v_sorted

    @field_validator("battery")
    @classmethod
    def _battery_consistent(cls, v: BatterySpec) -> BatterySpec:
        # Battery must be internally consistent: 0 <= minimum <= initial <= capacity.
        # No half-charged-by-default that exceeds max charge per hour, etc.
        if v.minimum_energy_kwh > v.capacity_kwh:
            raise ValueError(
                f"minimum_energy_kwh ({v.minimum_energy_kwh}) cannot exceed "
                f"capacity_kwh ({v.capacity_kwh})"
            )
        if v.initial_energy_kwh > v.capacity_kwh:
            raise ValueError(
                f"initial_energy_kwh ({v.initial_energy_kwh}) cannot exceed "
                f"capacity_kwh ({v.capacity_kwh})"
            )
        if v.initial_energy_kwh < v.minimum_energy_kwh:
            raise ValueError(
                f"initial_energy_kwh ({v.initial_energy_kwh}) cannot be less than "
                f"minimum_energy_kwh ({v.minimum_energy_kwh})"
            )
        return v


# ──────────── Structured directive adjustments (Section 04) ────────────

HoursList = Annotated[List[int], Field(min_length=1, max_length=24)]


class SolarReductionAdjustment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hours: HoursList
    factor: float = Field(..., ge=0.0, le=1.0)


class MinimumBatteryReserveAdjustment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hours: HoursList
    minimum_energy_kwh: float = Field(..., ge=0)


class NoChargeWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hours: HoursList


class NoDischargeWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hours: HoursList


class MaxGridWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hours: HoursList
    max_grid_kwh: float = Field(..., ge=0)


StructuredAdjustment = Union[
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment,
    None,
]


# ──────────── Response schema (Section 10) ────────────


class DirectiveInterpretationEntry(BaseModel):
    """One entry per operator note, in note_index order."""

    model_config = ConfigDict(extra="ignore")

    note_index: int = Field(..., ge=0)
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[
        Union[
            SolarReductionAdjustment,
            MinimumBatteryReserveAdjustment,
            NoChargeWindowAdjustment,
            NoDischargeWindowAdjustment,
            MaxGridWindowAdjustment,
        ]
    ] = None
    explanation: str = Field(..., min_length=1)


class HourlyPlanEntry(BaseModel):
    """One entry per hour 0..23."""

    model_config = ConfigDict(extra="ignore")

    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: BatteryAction
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float = Field(..., ge=0)


class OptimizeResponse(BaseModel):
    """Top-level response body (Section 10)."""

    model_config = ConfigDict(extra="ignore")

    scenario_id: str
    directive_interpretation: List[DirectiveInterpretationEntry] = Field(
        ..., min_length=1, max_length=3
    )
    hourly_plan: List[HourlyPlanEntry] = Field(..., min_length=24, max_length=24)
    total_grid_kwh: float = Field(..., ge=0)
    total_cost_bdt: float = Field(..., ge=0)
    peak_grid_kwh: float = Field(..., ge=0)
    plan_summary: str = Field(..., min_length=1)


# ──────────── Health response (Section 06.2) ────────────


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
