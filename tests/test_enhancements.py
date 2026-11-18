import pytest
from pyomo.environ import Var, value

from common.milp_model import build_dispatch_model
from common.sample_data import default_case
from common.schemas import FuelCurvePoint, Horizon, HorizonName, SolverSettings
from common.solvers import SolverFactory
from hourly_plan.planner import HourlyPlanner


@pytest.mark.parametrize('power', [0, 80, 140, 200, 260, 320, 370, 420])
@pytest.mark.parametrize('rates', [[25, 43, 65, 86], [25, 55, 60, 86]])
def test_compact_fuel_curve_is_exact_even_with_nonconvex_rates(power, rates):
    case = default_case()
    case.generators = case.generators[:1]
    gen = case.generators[0]
    gen.fuel_curve = [FuelCurvePoint(power_kw=p, liters_per_hour=f)
                      for p, f in zip([80, 200, 320, 420], rates)]
    gen.initial_on = power > 0
    gen.initial_power_kw = power
    gen.initial_up_steps = gen.initial_down_steps = 10
    gen.fuel_price_per_liter = 0  # Equality must hold without a fuel objective.
    case.horizon_configs[HorizonName.hourly].forecast.reserve_fraction = 0
    model = build_dispatch_model(case, Horizon(name=HorizonName.hourly, steps=1, interval_minutes=15))
    model.power['dg1', 0].fix(power)
    report = SolverFactory.solve(model, SolverSettings(name='highs', mip_gap=0))
    assert report.has_solution
    expected = 0
    for a, b in zip(gen.fuel_curve, gen.fuel_curve[1:]):
        if a.power_kw <= power <= b.power_kw:
            expected = a.liters_per_hour + (power-a.power_kw) / (b.power_kw-a.power_kw) * (b.liters_per_hour-a.liters_per_hour)
    assert value(model.fuel_lph['dg1', 0]) == pytest.approx(expected)
    assert len(model.fuel_segment) == 2


def test_result_analytics_and_costs_reconcile():
    plan = HourlyPlanner(default_case(), solver_name='highs').run()
    assert plan.status in {'solved', 'feasible'}
    assert sum(plan.cost_breakdown.values()) == pytest.approx(plan.solver_report.objective, abs=1e-4)
    assert plan.energy_summary['demand_kwh'] == pytest.approx(sum(r['demand_kw']*.25 for r in plan.dispatch))
    assert plan.performance['binary_variables'] > 0
    assert plan.performance['total_seconds'] >= plan.performance['build_seconds']
    assert plan.performance['total_seconds'] >= plan.solver_report.elapsed_seconds


def test_default_model_has_fewer_fuel_binaries():
    case = default_case()
    model = build_dispatch_model(case, Horizon.hourly())
    assert sum(v.is_binary() for v in model.component_data_objects(Var)) == 128


@pytest.mark.parametrize('initial_on', [False, True])
@pytest.mark.parametrize('sequence', [(0,0,0), (0,1,1), (1,0,1), (1,1,0)])
def test_continuous_transitions_are_exact_even_when_rewarded(initial_on, sequence):
    case = default_case()
    case.generators = case.generators[:1]
    gen = case.generators[0]
    gen.initial_on = initial_on
    gen.initial_power_kw = gen.min_power_kw if initial_on else 0
    gen.initial_up_steps = gen.initial_down_steps = 10
    gen.min_up_steps = gen.min_down_steps = 1
    gen.ramp_up_kw_per_step = gen.ramp_down_kw_per_step = 1000
    case.grid.import_limit_kw = case.grid.export_limit_kw = 10000
    case.batteries = []
    model = build_dispatch_model(case, Horizon(name='hourly', steps=3, interval_minutes=15))
    for t, on in enumerate(sequence):
        model.unit_on[gen.id, t].fix(on)
    # A negative transition cost would exploit any fractional simultaneous
    # start/stop loophole. The status gates must still force exact transitions.
    model.objective.set_value(-sum(model.startup[gen.id,t]+model.shutdown[gen.id,t] for t in model.T))
    report = SolverFactory.solve(model, SolverSettings(name='highs', mip_gap=0))
    assert report.has_solution
    previous = int(initial_on)
    for t, on in enumerate(sequence):
        assert value(model.startup[gen.id,t]) == pytest.approx(max(0,on-previous))
        assert value(model.shutdown[gen.id,t]) == pytest.approx(max(0,previous-on))
        previous = on
