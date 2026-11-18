from __future__ import annotations

from enum import Enum
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field, model_validator


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


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
        if (not self.initial_on and self.initial_power_kw != 0) or (self.initial_on and not self.min_power_kw <= self.initial_power_kw <= self.max_power_kw):
            raise ValueError("initial power must agree with initial commitment and operating range")
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
        if self.terminal_soc is not None and not self.min_soc <= self.terminal_soc <= self.max_soc:
            raise ValueError("terminal SOC must be within operating range")
        return self


class FlexibleLoad(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    min_kw: float = Field(ge=0)
    max_kw: float = Field(gt=0)
    shiftable_energy_kwh: float = Field(default=0, ge=0)
    adjustment_cost_per_kwh: float = Field(default=0.02, ge=0)

    @model_validator(mode="after")
    def validate_limits(self):
        if self.min_kw > self.max_kw:
            raise ValueError("flexible load min must not exceed max")
        if self.shiftable_energy_kwh and not self.min_kw * 24 <= self.shiftable_energy_kwh <= self.max_kw * 24:
            raise ValueError("daily flexible energy cannot be met within power limits")
        return self


class GridConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    import_limit_kw: float = Field(ge=0)
    export_limit_kw: float = Field(ge=0)
    import_price_per_kwh: float = Field(default=0.25, ge=0)
    export_price_per_kwh: float = Field(default=0.05, ge=0)


class NetworkModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "默认园区电网模型"
    base_mva: float = Field(default=1.0, gt=0)
    buses: list[dict[str, Any]] = Field(default_factory=list)
    lines: list[dict[str, Any]] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class OptimizationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fuel_cost_multiplier: float = Field(default=1.0, ge=0)
    startup_cost_multiplier: float = Field(default=1.0, ge=0)
    curtailment_penalty: float = Field(default=0.08, ge=0)
    reserve_penalty: float = Field(default=0.01, ge=0)
    lost_load_penalty: float = Field(default=10000.0, ge=0)
    baseline_deviation_penalty: float = Field(default=0.2, ge=0)
    storage_degradation_multiplier: float = Field(default=1.0, ge=0)


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


class HorizonOptimization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    optimization: OptimizationParameters = Field(default_factory=OptimizationParameters)
    solver: Literal["cplex", "highs", "cbc"] = "cplex"
    time_limit_seconds: float = Field(default=30, gt=0, le=3600)
    mip_gap: float = Field(default=0.01, ge=0, lt=1)


class HorizonInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_interval_minutes: int = Field(default=60, gt=0)
    forecast: Forecast
    start_time: datetime | None = None

    @model_validator(mode='after')
    def aware_time(self):
        if self.start_time is not None and self.start_time.utcoffset() is None:
            raise ValueError('start_time must include a timezone')
        return self


class HorizonConfig(HorizonInputs, HorizonOptimization):
    """Combined solve snapshot; individual web pages edit only their section."""


class DeviceParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generators: list[DieselGenerator] = Field(min_length=1)
    renewables: list[Renewable] = Field(default_factory=list)
    batteries: list[Battery] = Field(default_factory=list)
    flexible_loads: list[FlexibleLoad] = Field(default_factory=list)
    grid: GridConnection
    fuel_price_per_liter: float = Field(default=1, ge=0)

    @model_validator(mode="after")
    def unique_ids(self):
        for items in (self.generators, self.renewables, self.batteries, self.flexible_loads):
            if len({item.id for item in items}) != len(items):
                raise ValueError("device IDs must be unique within each type")
        return self


class CaseData(DeviceParameters):
    model_config = ConfigDict(extra="forbid")
    generators: list[DieselGenerator] = Field(min_length=1)
    renewables: list[Renewable] = Field(default_factory=list)
    batteries: list[Battery] = Field(default_factory=list)
    flexible_loads: list[FlexibleLoad] = Field(default_factory=list)
    grid: GridConnection
    forecast: Forecast
    fuel_price_per_liter: float = Field(default=1.0, ge=0)
    optimization: OptimizationParameters = Field(default_factory=OptimizationParameters)
    network_model: NetworkModel = Field(default_factory=NetworkModel)
    horizon_configs: dict[HorizonName, HorizonConfig] = Field(default_factory=dict)

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
        config = self.horizon_configs.get(horizon.name)
        source = config.forecast if config else self.forecast
        source_interval = config.input_interval_minutes if config else 60
        if source_interval == horizon.interval_minutes and len(source.demand_kw) >= horizon.steps:
            return {key: list(getattr(source, key)[:horizon.steps]) for key in ("demand_kw", "wind_kw", "pv_kw")}
        import numpy as np

        source_x = np.arange(len(source.demand_kw), dtype=float) * source_interval / 60.0
        target_x = np.arange(0, target_hours, horizon.step_hours, dtype=float)
        return {
            key: np.interp(target_x, source_x, np.asarray(getattr(source, key), dtype=float)).tolist()
            for key in ("demand_kw", "wind_kw", "pv_kw")
        }

    def config_for(self, horizon: Horizon | HorizonName | str) -> HorizonConfig:
        name = horizon.name if isinstance(horizon, Horizon) else HorizonName(horizon)
        config = self.horizon_configs.get(name)
        return config or HorizonConfig(forecast=self.forecast, optimization=self.optimization)


class SolverSettings(BaseModel):
    name: str = "cplex"
    time_limit_seconds: float = Field(default=30.0, gt=0)
    mip_gap: float = Field(default=0.01, ge=0, lt=1)
    require_milp: bool = True


class PlanRequest(BaseModel):
    solver: str | None = None
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
    has_solution: bool = False


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"
    step: int | None = None


class PlanValidationReport(BaseModel):
    plan_id: str
    valid: bool
    checked_at: str
    issues: list[ValidationIssue] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)


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
    parent_plan_id: str | None = None
    input_snapshot: CaseData | None = None
    energy_summary: dict[str, float] = Field(default_factory=dict)
    cost_breakdown: dict[str, float] = Field(default_factory=dict)
    performance: dict[str, float] = Field(default_factory=dict)


class ControlState(BaseModel):
    auto_hourly_enabled: bool = True
    last_published_plan_id: str | None = None
    last_executed_plan_id: str | None = None
    previous_published_plan_id: str | None = None


class ControlEvent(BaseModel):
    action: str
    plan_id: str | None = None
    detail: str = ""
    created_at: str
    kind: HorizonName | None = None
