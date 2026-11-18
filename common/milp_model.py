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
    segment_indices = {g.id: range(len(g.fuel_curve) - 1) for g in case.generators}
    renewable_capacity = {kind: sum(r.capacity_kw for r in case.renewables if r.kind == kind) for kind in ('wind', 'pv')}
    config = case.config_for(horizon)
    model._case = case
    model._horizon = horizon
    model._forecast = forecast

    model.unit_on = Var(model.G, model.T, domain=Binary)
    # Transition and the two status gates below force exact 0/1 starts/stops
    # from binary unit_on; separate binary branching is unnecessary.
    model.startup = Var(model.G, model.T, bounds=(0, 1))
    model.shutdown = Var(model.G, model.T, bounds=(0, 1))
    model.power = Var(model.G, model.T, domain=NonNegativeReals)
    model.fuel_lph = Var(model.G, model.T, domain=NonNegativeReals)

    segment_ids = [(g.id, s) for g in case.generators for s in segment_indices[g.id]]
    model.SEG = Set(dimen=2, initialize=segment_ids)
    model.FUEL_GATE = Set(dimen=2, initialize=[(g.id, s) for g in case.generators for s in range(len(g.fuel_curve)-2)])
    model.fuel_segment = Var(model.FUEL_GATE, model.T, domain=Binary)
    model.fuel_fraction = Var(model.SEG, model.T, bounds=(0, 1))
    model.fuel_segment_on = Expression(model.G, model.T, rule=lambda m, g, t: m.unit_on[g, t])

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
    model.generator_reserve = Var(model.G, model.T, domain=NonNegativeReals)
    model.battery_reserve = Var(model.B, model.T, domain=NonNegativeReals)
    model.grid_reserve = Var(model.T, domain=NonNegativeReals)
    model.lost_load = Var(model.T, domain=NonNegativeReals)

    # Incremental formulation: the next segment is usable only after the
    # previous is full. Exact for convex AND nonconvex curves, even at zero cost.
    # N points need N-2 binaries instead of N-1; two points need none.
    model.fuel_first = Constraint(model.G, model.T, rule=lambda m,g,t: m.fuel_fraction[g,0,t] <= m.unit_on[g,t])
    model.fuel_full = Constraint(model.FUEL_GATE, model.T, rule=lambda m,g,s,t: m.fuel_fraction[g,s,t] >= m.fuel_segment[g,s,t])
    model.fuel_next = Constraint(model.FUEL_GATE, model.T, rule=lambda m,g,s,t: m.fuel_fraction[g,s+1,t] <= m.fuel_segment[g,s,t])
    # fuel_full and fuel_next already imply monotone segment gates, including
    # in the LP relaxation; no duplicate chain constraints are needed.

    def power_curve_rule(m: ConcreteModel, g: str, t: int) -> Any:
        points = generators[g].fuel_curve
        return m.power[g, t] == points[0].power_kw*m.unit_on[g,t] + sum(m.fuel_fraction[g,s,t]*(points[s+1].power_kw-points[s].power_kw) for s in segment_indices[g])

    model.fuel_curve_power_link = Constraint(model.G, model.T, rule=power_curve_rule)

    def fuel_curve_rule(m: ConcreteModel, g: str, t: int) -> Any:
        points = generators[g].fuel_curve
        return m.fuel_lph[g, t] == points[0].liters_per_hour*m.unit_on[g,t] + sum(m.fuel_fraction[g,s,t]*(points[s+1].liters_per_hour-points[s].liters_per_hour) for s in segment_indices[g])

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
    model.startup_status = Constraint(model.G, model.T, rule=lambda m, g, t: m.startup[g, t] <= m.unit_on[g, t])
    model.shutdown_status = Constraint(model.G, model.T, rule=lambda m, g, t: m.shutdown[g, t] <= 1 - m.unit_on[g, t])

    def initial_status_lock_rule(m: ConcreteModel, g: str, t: int) -> Any:
        gen = generators[g]
        if gen.initial_on:
            required_on_steps = max(0, gen.min_up_steps - gen.initial_up_steps)
            return m.unit_on[g, t] == 1 if t < required_on_steps else Constraint.Skip
        required_off_steps = max(0, gen.min_down_steps - gen.initial_down_steps)
        return m.unit_on[g, t] == 0 if t < required_off_steps else Constraint.Skip

    model.initial_status_lock = Constraint(model.G, model.T, rule=initial_status_lock_rule)

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
        total_capacity = renewable_capacity[renewables[r].kind]
        available = forecast[key][t] * renewables[r].capacity_kw / total_capacity
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
        return m.reserve[t] == sum(m.generator_reserve[g,t] for g in m.G) + sum(m.battery_reserve[b,t] for b in m.B) + m.grid_reserve[t]

    model.reserve_definition = Constraint(model.T, rule=reserve_rule)
    model.reserve_generator_headroom = Constraint(model.G, model.T, rule=lambda m,g,t: m.generator_reserve[g,t] <= generators[g].max_power_kw*m.unit_on[g,t]-m.power[g,t])
    model.reserve_generator_ramp = Constraint(model.G, model.T, rule=lambda m,g,t: m.generator_reserve[g,t] <= generators[g].ramp_up_kw_per_step)
    model.reserve_battery_power = Constraint(model.B, model.T, rule=lambda m,b,t: m.battery_reserve[b,t] <= batteries[b].max_discharge_kw-m.discharge[b,t])
    model.reserve_battery_energy = Constraint(model.B, model.T, rule=lambda m,b,t: m.battery_reserve[b,t]*horizon.step_hours <= (m.soc[b,t]-batteries[b].min_soc*batteries[b].capacity_kwh)*batteries[b].discharge_efficiency)
    model.reserve_grid_headroom = Constraint(model.T, rule=lambda m,t: m.grid_reserve[t] <= case.grid.import_limit_kw-m.grid_import[t])
    model.reserve_requirement = Constraint(model.T, rule=lambda m, t: m.reserve[t] >= forecast["demand_kw"][t] * config.forecast.reserve_fraction)
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
        baseline_values = {g: baseline.get(g, [0.0] * horizon.steps) for g in generators}
        baseline_deviation = Var(model.G, model.T, domain=NonNegativeReals)
        model.baseline_deviation = baseline_deviation
        model.baseline_upper = Constraint(model.G, model.T, rule=lambda m, g, t: m.baseline_deviation[g, t] >= m.power[g, t] - baseline_values[g][t])
        model.baseline_lower = Constraint(model.G, model.T, rule=lambda m, g, t: m.baseline_deviation[g, t] >= baseline_values[g][t] - m.power[g, t])

    def objective_rule(m: ConcreteModel) -> Any:
        params = config.optimization
        fuel_cost = sum(params.fuel_cost_multiplier * m.fuel_lph[g, t] * generators[g].fuel_price_per_liter * horizon.step_hours for g in m.G for t in m.T)
        startup_cost = sum(params.startup_cost_multiplier * (generators[g].startup_cost * m.startup[g, t] + generators[g].shutdown_cost * m.shutdown[g, t]) for g in m.G for t in m.T)
        grid_cost = sum(case.grid.import_price_per_kwh * m.grid_import[t] * horizon.step_hours - case.grid.export_price_per_kwh * m.grid_export[t] * horizon.step_hours for t in m.T)
        storage_cost = sum(params.storage_degradation_multiplier * batteries[b].degradation_cost_per_kwh * (m.charge[b, t] + m.discharge[b, t]) * horizon.step_hours for b in m.B for t in m.T)
        curtail_cost = sum(params.curtailment_penalty * m.renewable_curtailment[r, t] * horizon.step_hours for r in m.R for t in m.T)
        reserve_cost = sum(params.reserve_penalty * m.reserve[t] * horizon.step_hours for t in m.T)
        lost_cost = sum(params.lost_load_penalty * m.lost_load[t] * horizon.step_hours for t in m.T)
        deviation_cost = 0 if baseline_deviation is None else sum(params.baseline_deviation_penalty * m.baseline_deviation[g, t] * horizon.step_hours for g in m.G for t in m.T)
        terms = dict(fuel=fuel_cost, startup=startup_cost, grid=grid_cost, storage=storage_cost,
                     curtailment=curtail_cost, reserve=reserve_cost, lost_load=lost_cost, baseline=deviation_cost)
        m.cost_terms = Expression(list(terms), rule=lambda m, key: terms[key])
        return sum(m.cost_terms.values())

    model.objective = Objective(rule=objective_rule, sense=minimize)
    return model
