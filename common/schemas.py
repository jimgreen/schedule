from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FuelCurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    power_kw: float = Field(gt=0)
    liters_per_hour: float = Field(gt=0)


class DieselGenerator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    fuel_type: Literal["diesel"] = "diesel"
    min_power_kw: float = Field(ge=0)
    max_power_kw: float = Field(gt=0)
    ramp_up_kw_per_step: float = Field(gt=0)
    ramp_down_kw_per_step: float = Field(gt=0)
    min_up_steps: int = Field(default=1, ge=1)
    min_down_steps: int = Field(default=1, ge=1)
    startup_cost: float = Field(default=0, ge=0)
    shutdown_cost: float = Field(default=0, ge=0)
    fuel_price_per_liter: float = Field(default=1.0, ge=0)
    fuel_curve: list[FuelCurvePoint] = Field(min_length=2)
    initial_on: bool = False
    initial_power_kw: float = Field(default=0, ge=0)
    initial_up_steps: int = Field(default=0, ge=0)
    initial_down_steps: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_curve(self) -> "DieselGenerator":
        if self.min_power_kw > self.max_power_kw:
            raise ValueError("min_power_kw must be <= max_power_kw")
        powers = [point.power_kw for point in self.fuel_curve]
        if powers != sorted(set(powers)):
            raise ValueError("fuel curve power points must be strictly increasing")
        if powers[0] > self.min_power_kw or powers[-1] < self.max_power_kw:
            raise ValueError("fuel curve must cover generator operating range")
        return self


class Renewable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    kind: Literal["wind", "pv"]
    capacity_kw: float = Field(gt=0)


class Battery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    capacity_kwh: float = Field(gt=0)
    max_charge_kw: float = Field(gt=0)
    max_discharge_kw: float = Field(gt=0)
    charge_efficiency: float = Field(gt=0, le=1)
    discharge_efficiency: float = Field(gt=0, le=1)
    min_soc: float = Field(ge=0, le=1)
    max_soc: float = Field(gt=0, le=1)
    initial_soc: float = Field(ge=0, le=1)
    terminal_soc: float | None = Field(default=None, ge=0, le=1)
    degradation_cost_per_kwh: float = Field(default=0.01, ge=0)

    @model_validator(mode="after")
    def validate_soc(self) -> "Battery":
        if self.min_soc > self.max_soc or not self.min_soc <= self.initial_soc <= self.max_soc:
            raise ValueError("SOC values must satisfy min <= initial <= max")
        return self


class FlexibleLoad(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    min_kw: float = Field(ge=0)
    max_kw: float = Field(gt=0)
    shiftable_energy_kwh: float = Field(default=0, ge=0)
    adjustment_cost_per_kwh: float = Field(default=0.02, ge=0)


class GridConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    import_limit_kw: float = Field(gt=0)
    export_limit_kw: float = Field(ge=0)
    import_price_per_kwh: float = Field(default=0.25, ge=0)
    export_price_per_kwh: float = Field(default=0.05, ge=0)


class HorizonName(str, Enum):
    weekly = "weekly"
    daily = "daily"
    hourly = "hourly"


class Horizon(BaseModel):
    name: HorizonName
    steps: int = Field(gt=0)
    interval_minutes: int = Field(gt=0)
    execute_steps: int = Field(default=0, ge=0)

    @classmethod
    def weekly(cls) -> "Horizon":
        return cls(name=HorizonName.weekly, steps=168, interval_minutes=60)

    @classmethod
    def daily(cls) -> "Horizon":
        return cls(name=HorizonName.daily, steps=96, interval_minutes=15)

    @classmethod
    def hourly(cls) -> "Horizon":
        return cls(name=HorizonName.hourly, steps=16, interval_minutes=15, execute_steps=1)

    @property
    def step_hours(self) -> float:
        return self.interval_minutes / 60.0


class Forecast(BaseModel):
    model_config = ConfigDict(extra="forbid")
    demand_kw: list[float] = Field(min_length=1)
    wind_kw: list[float] = Field(min_length=1)
    pv_kw: list[float] = Field(min_length=1)
    reserve_fraction: float = Field(default=0.1, ge=0, le=1)

    @model_validator(mode="after")
    def validate_lengths(self) -> "Forecast":
        lengths = {len(self.demand_kw), len(self.wind_kw), len(self.pv_kw)}
        if len(lengths) != 1:
            raise ValueError("forecast arrays must have equal lengths")
        if any(value < 0 for values in (self.demand_kw, self.wind_kw, self.pv_kw) for value in values):
            raise ValueError("forecast values must be non-negative")
        return self


class CaseData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generators: list[DieselGenerator] = Field(min_length=1)
    renewables: list[Renewable] = Field(default_factory=list)
    batteries: list[Battery] = Field(default_factory=list)
    flexible_loads: list[FlexibleLoad] = Field(default_factory=list)
    grid: GridConnection
    forecast: Forecast
    fuel_price_per_liter: float = Field(default=1.0, ge=0)

    @property
    def horizons(self) -> dict[str, Horizon]:
        return {
            "weekly": Horizon.weekly(),
            "daily": Horizon.daily(),
            "hourly": Horizon.hourly(),
        }

    def forecast_for(self, horizon: Horizon) -> dict[str, list[float]]:
        """Return a deterministic profile at the requested interval and length.

        The sample case stores hourly data. Quarter-hour plans use linear
        interpolation, then select the requested leading window.
        """
        target_hours = horizon.steps * horizon.step_hours
        source = self.forecast
        if horizon.interval_minutes == 60:
            indices = [min(int(i), len(source.demand_kw) - 1) for i in range(horizon.steps)]
            return {key: [getattr(source, key)[i] for i in indices] for key in ("demand_kw", "wind_kw", "pv_kw")}
        import numpy as np

        source_x = np.arange(len(source.demand_kw), dtype=float)
        target_x = np.arange(0, target_hours, horizon.step_hours, dtype=float)
        return {
            key: np.interp(target_x, source_x, np.asarray(getattr(source, key), dtype=float)).tolist()
            for key in ("demand_kw", "wind_kw", "pv_kw")
        }


class SolverSettings(BaseModel):
    name: str = "cplex"
    time_limit_seconds: float = Field(default=30.0, gt=0)
    mip_gap: float = Field(default=0.01, ge=0, lt=1)
    require_milp: bool = True


class PlanRequest(BaseModel):
    solver: str = "cplex"
    time_limit_seconds: float | None = Field(default=None, gt=0)
    mip_gap: float | None = Field(default=None, ge=0, lt=1)
    parent_plan_id: str | None = None


class SolveReport(BaseModel):
    solver: str
    status: str
    termination: str
    objective: float | None = None
    mip_gap: float | None = None
    elapsed_seconds: float
    message: str = ""


class FuelSummary(BaseModel):
    total_liters: float
    interval_liters: list[float]
    by_generator_liters: dict[str, float]
    cumulative_liters: list[float]


class PlanResult(BaseModel):
    plan_id: str
    kind: HorizonName
    horizon_steps: int
    interval_minutes: int
    status: str
    dispatch: list[dict[str, Any]]
    executed_dispatch: list[dict[str, Any]]
    fuel_summary: FuelSummary
    solver_report: SolveReport
    created_at: str


class ControlState(BaseModel):
    auto_hourly_enabled: bool = True
    last_published_plan_id: str | None = None
    last_executed_plan_id: str | None = None


class ControlEvent(BaseModel):
    action: str
    plan_id: str | None = None
    detail: str = ""
    created_at: str
