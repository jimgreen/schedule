from __future__ import annotations

import math

from .schemas import (
    Battery,
    CaseData,
    DieselGenerator,
    FlexibleLoad,
    Forecast,
    FuelCurvePoint,
    GridConnection,
    NetworkModel,
    OptimizationParameters,
    Renewable,
)


def _profile(base: float, amplitude: float, phase: float = 0.0) -> list[float]:
    values = []
    for hour in range(168):
        daily = math.sin((hour % 24 - 7) * math.pi / 12)
        weekly = 0.08 * math.sin((hour / 168 + phase) * math.pi * 2)
        values.append(round(max(0.0, base + amplitude * daily + base * weekly), 3))
    return values


def default_case() -> CaseData:
    return CaseData(
        generators=[
            DieselGenerator(
                id="dg1", name="柴油机组 1", min_power_kw=80, max_power_kw=420,
                ramp_up_kw_per_step=180, ramp_down_kw_per_step=180,
                min_up_steps=2, min_down_steps=2, startup_cost=28, shutdown_cost=6,
                fuel_price_per_liter=7.5, initial_on=True, initial_power_kw=160,
                fuel_curve=[FuelCurvePoint(power_kw=80, liters_per_hour=25), FuelCurvePoint(power_kw=200, liters_per_hour=43), FuelCurvePoint(power_kw=320, liters_per_hour=65), FuelCurvePoint(power_kw=420, liters_per_hour=86)],
            ),
            DieselGenerator(
                id="dg2", name="柴油机组 2", min_power_kw=50, max_power_kw=260,
                ramp_up_kw_per_step=120, ramp_down_kw_per_step=120,
                min_up_steps=2, min_down_steps=2, startup_cost=20, shutdown_cost=5,
                fuel_price_per_liter=7.5, initial_on=False,
                fuel_curve=[FuelCurvePoint(power_kw=50, liters_per_hour=17), FuelCurvePoint(power_kw=120, liters_per_hour=28), FuelCurvePoint(power_kw=200, liters_per_hour=43), FuelCurvePoint(power_kw=260, liters_per_hour=56)],
            ),
        ],
        renewables=[
            Renewable(id="wind", name="风电", kind="wind", capacity_kw=240),
            Renewable(id="pv", name="光伏", kind="pv", capacity_kw=300),
        ],
        batteries=[
            Battery(id="bat1", name="储能 1", capacity_kwh=600, max_charge_kw=180, max_discharge_kw=180,
                    charge_efficiency=0.95, discharge_efficiency=0.95, min_soc=0.1, max_soc=0.95,
                    initial_soc=0.5, terminal_soc=0.5, degradation_cost_per_kwh=0.04),
        ],
        flexible_loads=[FlexibleLoad(id="flex1", name="可调负荷", min_kw=20, max_kw=100, shiftable_energy_kwh=1440)],
        grid=GridConnection(import_limit_kw=500, export_limit_kw=220, import_price_per_kwh=0.9, export_price_per_kwh=0.25),
        forecast=Forecast(
            demand_kw=_profile(520, 120),
            wind_kw=[max(0.0, 135 + 80 * math.sin((h + 4) * math.pi / 12)) for h in range(168)],
            pv_kw=[max(0.0, 300 * math.sin((h % 24 - 6) * math.pi / 12)) for h in range(168)],
            reserve_fraction=0.1,
        ),
        fuel_price_per_liter=7.5,
        optimization=OptimizationParameters(),
        network_model=NetworkModel(
            name="默认园区电网模型", base_mva=1.0,
            buses=[{"id": "B1", "name": "园区母线", "voltage_kv": 10.0}],
            lines=[], parameters={"frequency_hz": 50, "operating_mode": "island_or_grid"},
        ),
    )
