from common.milp_model import build_dispatch_model
from common.sample_data import default_case


def test_model_has_binary_commitment_and_fuel_segment_variables():
    case = default_case()
    model = build_dispatch_model(case, case.horizons["weekly"])
    assert hasattr(model, "unit_on")
    assert hasattr(model, "fuel_segment_on")
    assert model.T.last() == 167


def test_fuel_curve_is_linked_to_generator_output():
    case = default_case()
    model = build_dispatch_model(case, case.horizons["hourly"])
    assert hasattr(model, "fuel_lph")
    assert hasattr(model, "fuel_curve_power_link")
    assert hasattr(model, "fuel_curve_rate_link")


def test_model_has_power_balance_and_storage_constraints():
    case = default_case()
    model = build_dispatch_model(case, case.horizons["daily"])
    assert hasattr(model, "power_balance")
    assert hasattr(model, "soc_transition")
    assert hasattr(model, "reserve_requirement")
