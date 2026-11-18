from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_health_and_solver_catalog():
    assert client.get("/api/health").status_code == 200
    payload = client.get("/api/solver").json()
    assert {"cplex", "highs", "cbc"}.issubset(payload)


def test_default_case_and_control_state():
    assert client.get("/api/case").status_code == 200
    state = client.get("/api/control").json()
    assert state["auto_hourly_enabled"] is False


def test_unknown_solver_returns_milp_error():
    response = client.post("/api/hourly-plan/solve", json={"solver": "missing-solver"})
    assert response.status_code == 422
    assert "MILP" in response.json()["detail"]


def test_overview_is_database_backed_and_control_can_use_latest_plan():
    overview = client.get("/api/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert "plans" in body and "control" in body
    response = client.post("/api/control/pause")
    assert response.status_code == 409
    assert client.post("/api/control/resume").status_code == 409


def test_optimization_and_network_model_are_editable():
    params = client.put("/api/optimization-params", json={"lost_load_penalty": 12345}).json()
    assert params["lost_load_penalty"] == 12345
    model = client.put("/api/network-model", json={"name": "接口模型", "base_mva": 10, "buses": [{"id": "B1"}], "lines": [], "parameters": {"frequency_hz": 50}}).json()
    assert model["name"] == "接口模型"
    assert client.get("/api/network-model").json()["base_mva"] == 10


def test_plan_validation_and_lightweight_history():
    solved = client.post("/api/hourly-plan/solve", json={"solver": "highs"})
    assert solved.status_code == 200
    plan_id = solved.json()["plan_id"]
    report = client.post(f"/api/plans/id/{plan_id}/validate")
    assert report.status_code == 200
    body = report.json()
    assert body["plan_id"] == plan_id
    assert "metrics" in body and "fuel_total_liters" in body["metrics"]
    summaries = client.get("/api/plan-summaries?kind=hourly").json()["plans"]
    assert summaries and summaries[0]["plan_id"] == plan_id


def test_daily_plan_requires_weekly_parent_when_parent_is_given():
    response = client.post("/api/daily-plan/solve", json={"solver": "highs", "parent_plan_id": "missing"})
    assert response.status_code == 404


def test_daily_plan_uses_weekly_parent_baseline():
    weekly = client.post("/api/weekly-plan/solve", json={"solver": "highs"})
    assert weekly.status_code == 200
    parent_id = weekly.json()["plan_id"]
    daily = client.post("/api/daily-plan/solve", json={"solver": "highs", "parent_plan_id": parent_id})
    assert daily.status_code == 200
    body = daily.json()
    assert body["parent_plan_id"] == parent_id
    assert len(body["dispatch"]) == 96
