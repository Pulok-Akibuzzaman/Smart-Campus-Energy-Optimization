"""Pydantic data schemas for GridWise API contract."""

from typing import List, Optional, Literal, Union, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class HourInput(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0 to 23)")
    demand_kwh: float = Field(..., ge=0.0, description="Campus demand in kWh")
    solar_kwh: float = Field(..., ge=0.0, description="Forecasted solar generation in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0.0, description="Grid tariff in BDT/kWh")


class BatteryInput(BaseModel):
    capacity_kwh: float = Field(..., gt=0.0, description="Total battery capacity in kWh")
    initial_energy_kwh: float = Field(..., ge=0.0, description="Battery energy at start of hour 0")
    minimum_energy_kwh: float = Field(..., ge=0.0, description="Base minimum allowable battery energy")
    max_charge_kwh_per_hour: float = Field(..., ge=0.0, description="Max charging rate in kWh/h")
    max_discharge_kwh_per_hour: float = Field(..., ge=0.0, description="Max discharging rate in kWh/h")

    @model_validator(mode="after")
    def validate_battery_levels(self):
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        if self.initial_energy_kwh < self.minimum_energy_kwh:
            raise ValueError("initial_energy_kwh cannot be less than minimum_energy_kwh")
        return self


class ScenarioRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1, description="Unique scenario identifier")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1 to 3 operator notes")
    hours: List[HourInput] = Field(..., min_length=24, max_length=24, description="Exactly 24 hourly records")
    battery: BatteryInput = Field(..., description="Battery specifications")

    @field_validator("operator_notes")
    @classmethod
    def validate_operator_notes(cls, v: List[str]) -> List[str]:
        for idx, note in enumerate(v):
            if not note or not note.strip():
                raise ValueError(f"operator_notes[{idx}] cannot be empty")
        return v

    @field_validator("hours")
    @classmethod
    def validate_hours_sequence(cls, v: List[HourInput]) -> List[HourInput]:
        if len(v) != 24:
            raise ValueError(f"hours array must contain exactly 24 entries, got {len(v)}")
        seen_hours = set()
        for idx, h in enumerate(v):
            if h.hour != idx:
                raise ValueError(f"hours entries must be ordered 0..23; entry at index {idx} has hour {h.hour}")
            if h.hour in seen_hours:
                raise ValueError(f"Duplicate hour {h.hour} detected")
            seen_hours.add(h.hour)
        return v


# ---------------------------------------------------------------------------
# Directive & Response Models
# ---------------------------------------------------------------------------

AllowedDirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
]

AllowedBatteryAction = Literal["charge", "discharge", "idle"]


class DirectiveInterpretationEntry(BaseModel):
    note_index: int = Field(..., ge=0, description="Zero-based index of operator note")
    applies: bool = Field(..., description="True for non-no_op, False ONLY for no_op")
    directive_type: AllowedDirectiveType = Field(..., description="One of the 6 canonical directive types")
    structured_adjustment: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured parameter object, or null iff no_op"
    )
    explanation: str = Field(..., description="Concise explanation of the interpretation")

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.directive_type == "no_op":
            if self.applies:
                raise ValueError("applies must be false when directive_type is no_op")
            if self.structured_adjustment is not None:
                raise ValueError("structured_adjustment must be null when directive_type is no_op")
        else:
            if not self.applies:
                raise ValueError(f"applies must be true for non-no_op directive {self.directive_type}")
            if self.structured_adjustment is None:
                raise ValueError(f"structured_adjustment cannot be null for non-no_op directive {self.directive_type}")
        return self


class HourlyPlanEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0.0)
    solar_used_kwh: float = Field(..., ge=0.0)
    battery_action: AllowedBatteryAction
    battery_kwh: float = Field(..., ge=0.0)
    battery_energy_after_kwh: float = Field(..., ge=0.0)


class OptimizationResponse(BaseModel):
    scenario_id: str = Field(..., description="Echoes the request scenario_id")
    directive_interpretation: List[DirectiveInterpretationEntry] = Field(
        ...,
        description="Exactly one interpretation per note in note_index order"
    )
    hourly_plan: List[HourlyPlanEntry] = Field(
        ...,
        min_length=24,
        max_length=24,
        description="24 hourly entries for hours 0..23"
    )
    total_grid_kwh: float = Field(..., ge=0.0, description="Sum of grid_kwh over 24 hours")
    total_cost_bdt: float = Field(..., ge=0.0, description="Sum of hourly grid_kwh * tariff")
    peak_grid_kwh: float = Field(..., ge=0.0, description="Max grid_kwh in any hour")
    plan_summary: str = Field(..., description="Human readable summary of the operating strategy")


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
