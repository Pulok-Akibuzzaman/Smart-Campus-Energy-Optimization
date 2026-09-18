"""
models.py - Pydantic Schemas for Request & Response
Strictly matches Section 07 and Section 10 of the Problem Statement.
"""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field

class HourEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Unique integer from 0 to 23.")
    demand_kwh: float = Field(..., ge=0, description="Campus demand that must be supplied.")
    solar_kwh: float = Field(..., ge=0, description="Base solar energy available.")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Grid electricity price for this hour.")

class BatteryData(BaseModel):
    capacity_kwh: float = Field(..., gt=0, description="Maximum energy the battery can store.")
    initial_energy_kwh: float = Field(..., ge=0, description="Battery energy at start of hour 0.")
    minimum_energy_kwh: float = Field(..., ge=0, description="Base reserve level.")
    max_charge_kwh_per_hour: float = Field(..., ge=0, description="Maximum energy added per hour.")
    max_discharge_kwh_per_hour: float = Field(..., ge=0, description="Maximum energy removed per hour.")

class OptimizeEnergyRequest(BaseModel):
    scenario_id: str = Field(..., description="Unique synthetic scenario identifier.")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1-3 natural-language notes.")
    hours: List[HourEntry] = Field(..., min_length=24, max_length=24, description="Exactly 24 hourly intervals.")
    battery: BatteryData

class DirectiveInterpretation(BaseModel):
    note_index: int
    applies: bool
    directive_type: Literal[
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op"
    ]
    structured_adjustment: Optional[Dict[str, Any]] = None
    explanation: str

class HourlyPlanEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float = Field(..., ge=0)

class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str

class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
