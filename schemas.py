from typing import List, Literal, Optional, Union
from pydantic import BaseModel

# Input Schemas


class HourInput(BaseModel):
    hour: int
    demand_kwh: float
    solar_kwh: float
    tariff_bdt_per_kwh: float


class BatteryInput(BaseModel):
    capacity_kwh: float
    initial_energy_kwh: float
    minimum_energy_kwh: float
    max_charge_kwh_per_hour: float
    max_discharge_kwh_per_hour: float


class OptimizeEnergyRequest(BaseModel):
    scenario_id: str
    operator_notes: List[str]
    hours: List[HourInput]
    battery: BatteryInput


# Output Schemas
DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
]


class SolarReductionAdj(BaseModel):
    hours: List[int]
    factor: float


class MinReserveAdj(BaseModel):
    hours: List[int]
    minimum_energy_kwh: float


class WindowOnlyAdj(BaseModel):
    hours: List[int]


class MaxGridAdj(BaseModel):
    hours: List[int]
    max_grid_kwh: float


StructuredAdjustmentType = Union[SolarReductionAdj,
                                 MinReserveAdj, WindowOnlyAdj, MaxGridAdj, None]


class DirectiveInterpretationEntry(BaseModel):
    note_index: int
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: StructuredAdjustmentType = None
    explanation: str


class HourlyPlanEntry(BaseModel):
    hour: int
    grid_kwh: float
    solar_used_kwh: float
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float
    battery_energy_after_kwh: float


class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretationEntry]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
