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
    assert {"diesel_generators", "fuel_curve_points", "plans", "audit_events"}.issubset(tables)
