from fastapi.testclient import TestClient

from api.main import app


def test_all_plans_return_fuel_statistics():
    client = TestClient(app)
    for kind in ("weekly", "daily", "hourly"):
        response = client.post(f"/api/{kind}-plan/solve", json={"solver": "highs"})
        assert response.status_code == 200
        body = response.json()
        assert body["fuel_summary"]["total_liters"] >= 0
        assert len(body["fuel_summary"]["interval_liters"]) == body["horizon_steps"]
