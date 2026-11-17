from common.sample_data import default_case
from common.store import ScheduleStore


def test_sqlite_store_round_trips_case_and_has_schedule_tables(tmp_path):
    store = ScheduleStore(tmp_path / "schedule.db")
    case = default_case()
    store.save_case(case)
    loaded = store.load_case()
    assert loaded is not None
    assert loaded.generators[0].fuel_curve[1].liters_per_hour == case.generators[0].fuel_curve[1].liters_per_hour
    with store._connect() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"diesel_generators", "fuel_curve_points", "plans", "audit_events", "optimization_parameters", "network_models"}.issubset(tables)


def test_sqlite_store_round_trips_optimization_and_network_model(tmp_path):
    from common.schemas import NetworkModel, OptimizationParameters

    store = ScheduleStore(tmp_path / "schedule.db")
    store.save_optimization(OptimizationParameters(lost_load_penalty=12345))
    store.save_network_model(NetworkModel(name="测试模型", buses=[{"id": "B1"}]))
    assert store.load_optimization().lost_load_penalty == 12345
    assert store.load_network_model().name == "测试模型"
