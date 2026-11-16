from __future__ import annotations

from typing import Any

from pyomo.environ import (
    Binary,
    ConcreteModel,
    Constraint,
    Expression,
    NonNegativeReals,
    Objective,
    Reals,
    Set,
    Var,
    minimize,
    value,
)

from .schemas import CaseData, Horizon


def _previous(value_list: list[float], index: int, default: float) -> float:
    return default if index == 0 else value_list[index - 1]


def build_dispatch_model(case: CaseData, horizon: Horizon, baseline: dict[str, list[float]] | None = None) -> ConcreteModel:
    forecast = case.forecast_for(horizon)
    model = ConcreteModel(name=f"{horizon.name.value}_diesel_microgrid_milp")
    model.T = Set(initialize=range(horizon.steps), ordered=True)
    model.G = Set(initialize=[g.id for g in case.generators], ordered=True)
    model.R = Set(initialize=[r.id for r in case.renewables], ordered=True)
    model.B = Set(initialize=[b.id for b in case.batteries], ordered=True)
    model.F = Set(initialize=[f.id for f in case.flexible_loads], ordered=True)
    generators = {g.id: g for g in case.generators}
    renewables = {r.id: r for r in case.renewables}
    batteries = {b.id: b for b in case.batteries}
    flex_loads = {f.id: f for f in case.flexible_loads}
    model._case = case
    model._horizon = horizon
    model._forecast = forecast

    model.unit_on = Var(model.G, model.T, domain=Binary)
    model.startup = Var(model.G, model.T, domain=Binary)
    model.shutdown = Var(model.G, model.T, domain=Binary)
    model.power = Var(model.G, model.T, domain=NonNegativeReals)
    model.fuel_lph = Var(model.G, model.T, domain=NonNegativeReals)
    model.fuel_segment_on = Var(model.G, model.T, domain=Binary)

    segment_ids = {(g.id, s) for g in case.generators for s in range(len(g.fuel_curve) - 1)}
    breakpoint_ids = {(g.id, s) for g in case.generators for s in range(len(g.fuel_curve))}
    model.SEG = Set(dimen=2, initialize=segment_ids)
    model.BP = Set(dimen=2, initialize=breakpoint_ids)
    model.fuel_segment = Var(model.SEG, model.T, domain=Binary)
    model.fuel_lambda = Var(model.BP, model.T, domain=NonNegativeReals)

    model.renewable_dispatch = Var(model.R, model.T, domain=NonNegativeReals)
    model.renewable_curtailment = Var(model.R, model.T, domain=NonNegativeReals)
    model.charge = Var(model.B, model.T, domain=NonNegativeReals)
    model.discharge = Var(model.B, model.T, domain=NonNegativeReals)
    model.soc = Var(model.B, model.T, domain=NonNegativeReals)
    model.storage_charge_mode = Var(model.B, model.T, domain=Binary)
    model.grid_import = Var(model.T, domain=NonNegativeReals)
    model.grid_export = Var(model.T, domain=NonNegativeReals)
    model.grid_import_mode = Var(model.T, domain=Binary)
    model.flex_power = Var(model.F, model.T, domain=NonNegativeReals)
    model.reserve = Var(model.T, domain=NonNegativeReals)
    model.lost_load = Var(model.T, domain=NonNegativeReals)

    def segment_sum_rule(m: ConcreteModel, g: str, t: int) -> Any:
        return sum(m.fuel_segment[g, s, t] for gg, s in m.SEG if gg == g) == m.unit_on[g, t]

    model.segment_sum = Constraint(model.G, model.T, rule=segment_sum_rule)

    def lambda_sum_rule(m: ConcreteModel, g: str, t: int) -> Any:
        return sum(m.fuel_lambda[g, s, t] for gg, s in m.BP if gg == g) == m.unit_on[g, t]

    model.lambda_sum = Constraint(model.G, model.T, rule=lambda_sum_rule)

    def lambda_segment_rule(m: ConcreteModel, g: str, s: int, t: int) -> Any:
        return m.fuel_lambda[g, s, t] + m.fuel_lambda[g, s + 1, t] <= m.fuel_segment[g, s, t] + (1 - m.unit_on[g, t])

    model.lambda_segment = Constraint(model.SEG, model.T, rule=lambda_segment_rule)

    def power_curve_rule(m: ConcreteModel, g: str, t: int) -> Any:
        points = generators[g].fuel_curve
        return m.power[g, t] == sum(m.fuel_lambda[g, s, t] * points[s].power_kw for gg, s in m.BP if gg == g)

    model.fuel_curve_power_link = Constraint(model.G, model.T, rule=power_curve_rule)

    def fuel_curve_rule(m: ConcreteModel, g: str, t: int) -> Any:
        points = generators[g].fuel_curve
        return m.fuel_lph[g, t] == sum(m.fuel_lambda[g, s, t] * points[s].liters_per_hour for gg, s in m.BP if gg == g)

    model.fuel_curve_rate_link = Constraint(model.G, model.T, rule=fuel_curve_rule)

    model.generator_min_power = Constraint(model.G, model.T, rule=lambda m, g, t: m.power[g, t] >= generators[g].min_power_kw * m.unit_on[g, t])
    model.generator_max_power = Constraint(model.G, model.T, rule=lambda m, g, t: m.power[g, t] <= generators[g].max_power_kw * m.unit_on[g, t])

    def transition_rule(m: ConcreteModel, g: str, t: int) -> Any:
        gen = generators[g]
        previous_on = int(gen.initial_on)
        if t > 0:
            previous_on = m.unit_on[g, t - 1]
        return m.unit_on[g, t] - previous_on == m.startup[g, t] - m.shutdown[g, t]

    model.commitment_transition = Constraint(model.G, model.T, rule=transition_rule)
    model.start_stop_exclusive = Constraint(model.G, model.T, rule=lambda m, g, t: m.startup[g, t] + m.shutdown[g, t] <= 1)

    def ramp_up_rule(m: ConcreteModel, g: str, t: int) -> Any:
        gen = generators[g]
        previous = gen.initial_power_kw if t == 0 else m.power[g, t - 1]
        return m.power[g, t] - previous <= gen.ramp_up_kw_per_step

    def ramp_down_rule(m: ConcreteModel, g: str, t: int) -> Any:
        gen = generators[g]
        previous = gen.initial_power_kw if t == 0 else m.power[g, t - 1]
        return previous - m.power[g, t] <= gen.ramp_down_kw_per_step

    model.ramp_up = Constraint(model.G, model.T, rule=ramp_up_rule)
    model.ramp_down = Constraint(model.G, model.T, rule=ramp_down_rule)

    def min_up_rule(m: ConcreteModel, g: str, t: int) -> Any:
        start = max(0, t - generators[g].min_up_steps + 1)
        return sum(m.startup[g, k] for k in range(start, t + 1)) <= m.unit_on[g, t]

    def min_down_rule(m: ConcreteModel, g: str, t: int) -> Any:
        start = max(0, t - generators[g].min_down_steps + 1)
        return sum(m.shutdown[g, k] for k in range(start, t + 1)) <= 1 - m.unit_on[g, t]

    model.minimum_up_time = Constraint(model.G, model.T, rule=min_up_rule)
    model.minimum_down_time = Constraint(model.G, model.T, rule=min_down_rule)

    def renewable_available_rule(m: ConcreteModel, r: str, t: int) -> Any:
        key = "wind_kw" if renewables[r].kind == "wind" else "pv_kw"
        available = forecast[key][t]
        return m.renewable_dispatch[r, t] + m.renewable_curtailment[r, t] == min(available, renewables[r].capacity_kw)

    model.renewable_available = Constraint(model.R, model.T, rule=renewable_available_rule)

    def storage_soc_rule(m: ConcreteModel, b: str, t: int) -> Any:
        battery = batteries[b]
        previous_soc = battery.initial_soc * battery.capacity_kwh if t == 0 else m.soc[b, t - 1]
        return m.soc[b, t] == previous_soc + battery.charge_efficiency * m.charge[b, t] * horizon.step_hours - m.discharge[b, t] * horizon.step_hours / battery.discharge_efficiency

    model.soc_transition = Constraint(model.B, model.T, rule=storage_soc_rule)

    model.storage_soc_min = Constraint(model.B, model.T, rule=lambda m, b, t: m.soc[b, t] >= batteries[b].min_soc * batteries[b].capacity_kwh)
    model.storage_soc_max = Constraint(model.B, model.T, rule=lambda m, b, t: m.soc[b, t] <= batteries[b].max_soc * batteries[b].capacity_kwh)
    model.charge_mode_limit = Constraint(model.B, model.T, rule=lambda m, b, t: m.charge[b, t] <= batteries[b].max_charge_kw * m.storage_charge_mode[b, t])
    model.discharge_mode_limit = Constraint(model.B, model.T, rule=lambda m, b, t: m.discharge[b, t] <= batteries[b].max_discharge_kw * (1 - m.storage_charge_mode[b, t]))

    def terminal_soc_rule(m: ConcreteModel, b: str) -> Any:
        terminal = batteries[b].terminal_soc
        return Constraint.Skip if terminal is None else m.soc[b, horizon.steps - 1] == terminal * batteries[b].capacity_kwh

    model.terminal_soc = Constraint(model.B, rule=terminal_soc_rule)

    model.grid_import_limit = Constraint(model.T, rule=lambda m, t: m.grid_import[t] <= case.grid.import_limit_kw * m.grid_import_mode[t])
    model.grid_export_limit = Constraint(model.T, rule=lambda m, t: m.grid_export[t] <= case.grid.export_limit_kw * (1 - m.grid_import_mode[t]))

    model.flexible_load_min = Constraint(model.F, model.T, rule=lambda m, f, t: m.flex_power[f, t] >= flex_loads[f].min_kw)
    model.flexible_load_max = Constraint(model.F, model.T, rule=lambda m, f, t: m.flex_power[f, t] <= flex_loads[f].max_kw)
    for flex in case.flexible_loads:
        if flex.shiftable_energy_kwh:
            target_energy = flex.shiftable_energy_kwh * horizon.steps * horizon.step_hours / 24.0
            setattr(model, f"flex_energy_{flex.id}", Constraint(expr=sum(model.flex_power[flex.id, t] * horizon.step_hours for t in model.T) == target_energy))

    def reserve_rule(m: ConcreteModel, t: int) -> Any:
        required = forecast["demand_kw"][t] * case.forecast.reserve_fraction
        available = sum(generators[g].max_power_kw * m.unit_on[g, t] - m.power[g, t] for g in m.G)
        available += sum(batteries[b].max_discharge_kw - m.discharge[b, t] for b in m.B)
        available += case.grid.import_limit_kw - m.grid_import[t]
        return m.reserve[t] == available

    model.reserve_definition = Constraint(model.T, rule=reserve_rule)
    model.reserve_requirement = Constraint(model.T, rule=lambda m, t: m.reserve[t] >= forecast["demand_kw"][t] * case.forecast.reserve_fraction)
    model.lost_load_limit = Constraint(model.T, rule=lambda m, t: m.lost_load[t] <= forecast["demand_kw"][t] * 0.5)

    def power_balance_rule(m: ConcreteModel, t: int) -> Any:
        generation = sum(m.power[g, t] for g in m.G)
        renewable = sum(m.renewable_dispatch[r, t] for r in m.R)
        battery = sum(m.discharge[b, t] - m.charge[b, t] for b in m.B)
        flexible = sum(m.flex_power[f, t] for f in m.F)
        return generation + renewable + battery + m.grid_import[t] + m.lost_load[t] == forecast["demand_kw"][t] + flexible + m.grid_export[t]

    model.power_balance = Constraint(model.T, rule=power_balance_rule)

    baseline_deviation = None
    if baseline:
        baseline_deviation = Var(model.G, model.T, domain=NonNegativeReals)
        model.baseline_deviation = baseline_deviation
        model.baseline_upper = Constraint(model.G, model.T, rule=lambda m, g, t: m.baseline_deviation[g, t] >= m.power[g, t] - baseline.get(g, [0.0] * horizon.steps)[t])
        model.baseline_lower = Constraint(model.G, model.T, rule=lambda m, g, t: m.baseline_deviation[g, t] >= baseline.get(g, [0.0] * horizon.steps)[t] - m.power[g, t])

    def objective_rule(m: ConcreteModel) -> Any:
        fuel_cost = sum(m.fuel_lph[g, t] * generators[g].fuel_price_per_liter * horizon.step_hours for g in m.G for t in m.T)
        startup_cost = sum(generators[g].startup_cost * m.startup[g, t] + generators[g].shutdown_cost * m.shutdown[g, t] for g in m.G for t in m.T)
        grid_cost = sum(case.grid.import_price_per_kwh * m.grid_import[t] * horizon.step_hours - case.grid.export_price_per_kwh * m.grid_export[t] * horizon.step_hours for t in m.T)
        storage_cost = sum(batteries[b].degradation_cost_per_kwh * (m.charge[b, t] + m.discharge[b, t]) * horizon.step_hours for b in m.B for t in m.T)
        curtail_cost = sum(0.08 * m.renewable_curtailment[r, t] * horizon.step_hours for r in m.R for t in m.T)
        reserve_cost = sum(0.01 * m.reserve[t] * horizon.step_hours for t in m.T)
        lost_cost = sum(10000.0 * m.lost_load[t] * horizon.step_hours for t in m.T)
        deviation_cost = 0 if baseline_deviation is None else sum(0.2 * m.baseline_deviation[g, t] for g in m.G for t in m.T)
        return fuel_cost + startup_cost + grid_cost + storage_cost + curtail_cost + reserve_cost + lost_cost + deviation_cost

    model.objective = Objective(rule=objective_rule, sense=minimize)
    return model
