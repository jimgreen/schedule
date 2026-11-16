from common.sample_data import default_case
from common.schemas import Horizon, SolverSettings


def test_default_case_uses_diesel_and_valid_fuel_curve():
    case = default_case()
    assert case.generators[0].fuel_type == "diesel"
    assert len(case.generators[0].fuel_curve) >= 3
    assert all(p.power_kw < q.power_kw for p, q in zip(case.generators[0].fuel_curve, case.generators[0].fuel_curve[1:]))


def test_horizon_lengths_match_requirements():
    assert Horizon.weekly().steps == 168
    assert Horizon.daily().steps == 96
    assert Horizon.hourly().steps == 16


def test_solver_settings_require_milp():
    settings = SolverSettings(name="highs", mip_gap=0.01)
    assert settings.require_milp is True
