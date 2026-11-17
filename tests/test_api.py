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
    assert state["auto_hourly_enabled"] is True


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
    assert response.status_code == 200
    assert response.json()["auto_hourly_enabled"] is False
    assert client.post("/api/control/resume").json()["auto_hourly_enabled"] is True


def test_optimization_and_network_model_are_editable():
    params = client.put("/api/optimization-params", json={"lost_load_penalty": 12345}).json()
    assert params["lost_load_penalty"] == 12345
    model = client.put("/api/network-model", json={"name": "接口模型", "base_mva": 10, "buses": [{"id": "B1"}], "lines": [], "parameters": {"frequency_hz": 50}}).json()
    assert model["name"] == "接口模型"
    assert client.get("/api/network-model").json()["base_mva"] == 10
