# Schedule MILP 调度平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI plus native HTML/JavaScript scheduling platform with three all-MILP planning horizons for diesel generators, renewables, storage, flexible load, and grid exchange.

**Architecture:** A shared Pyomo MILP builder supplies asset variables, fuel-curve interpolation, operating constraints, and objective terms. `weekly_plan`, `daily_plan`, and `hourly_plan` wrap the shared builder with 168 hourly, 96 quarter-hour, and 16 quarter-hour rolling horizons. FastAPI exposes plan, solver, and control endpoints; the fixed viewport frontend uses tabs and internal pagination instead of scrollbars.

**Tech Stack:** Python 3.11+, Pyomo, FastAPI, Uvicorn, Pydantic, NumPy, SciPy/HiGHS, optional CPLEX and CBC, native HTML/CSS/JavaScript, SVG charts, pytest/httpx.

---

### Task 1: Create the Python package and test baseline

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `common/__init__.py`
- Create: `weekly_plan/__init__.py`
- Create: `daily_plan/__init__.py`
- Create: `hourly_plan/__init__.py`
- Create: `api/__init__.py`
- Create: `tests/test_imports.py`

- [ ] **Step 1: Write the failing import test**

```python
def test_schedule_packages_import():
    import common
    import weekly_plan
    import daily_plan
    import hourly_plan
    import api

    assert common is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_imports.py -q`
Expected: FAIL because the packages do not exist.

- [ ] **Step 3: Add package metadata and empty package modules**

`pyproject.toml` must define the package name, Python version, pytest configuration, and dependencies. `requirements.txt` must contain `pyomo`, `fastapi`, `uvicorn[standard]`, `pydantic`, `numpy`, `scipy`, `highspy`, `pytest`, and `httpx`. Each package `__init__.py` exports no runtime side effects.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_imports.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.txt common weekly_plan daily_plan hourly_plan api tests/test_imports.py
git commit -m "build: scaffold schedule packages"
```

### Task 2: Define assets, forecasts, plans, and solver settings

**Files:**
- Create: `common/schemas.py`
- Create: `common/sample_data.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write tests for diesel fuel points and horizon lengths**

```python
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


def test_solver_settings_reject_non_milp_mode():
    settings = SolverSettings(name="highs", mip_gap=0.01)
    assert settings.require_milp is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_schemas.py -q`
Expected: FAIL because schema classes are missing.

- [ ] **Step 3: Implement typed schemas**

Define Pydantic models for `FuelCurvePoint(power_kw, liters_per_hour)`, `DieselGenerator` (min/max power, ramp limits, min up/down, startup/shutdown cost, fuel curve), `Renewable`, `Battery`, `FlexibleLoad`, `GridConnection`, `Forecast`, `CaseData`, `Horizon`, `SolverSettings`, `PlanRequest`, `PlanResult`, `FuelSummary`, and `ControlEvent`. `Horizon.weekly()` returns 168 one-hour steps, `Horizon.daily()` returns 96 fifteen-minute steps, and `Horizon.hourly()` returns 16 fifteen-minute steps with `execute_steps=1`. Validate monotonic fuel-curve powers and positive capacities. `default_case()` must provide two diesel generators, wind, PV, storage, flexible load, grid limits, and deterministic demand/renewable forecasts.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/schemas.py common/sample_data.py tests/test_schemas.py
git commit -m "feat: define scheduling assets and horizons"
```

### Task 3: Add the solver adapter with strict MILP selection

**Files:**
- Create: `common/solvers.py`
- Create: `tests/test_solvers.py`

- [ ] **Step 1: Write solver discovery and unavailable-solver tests**

```python
from common.solvers import SolverFactory, SolverUnavailable


def test_solver_catalog_contains_milp_solvers():
    catalog = SolverFactory.catalog()
    assert {"cplex", "highs", "cbc"}.issubset(catalog)
    assert all(item.require_milp for item in catalog.values())


def test_unknown_solver_fails_without_lp_fallback():
    try:
        SolverFactory.create("missing-solver")
    except SolverUnavailable as exc:
        assert "MILP" in str(exc)
    else:
        raise AssertionError("expected SolverUnavailable")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_solvers.py -q`
Expected: FAIL because the adapter is missing.

- [ ] **Step 3: Implement the adapter**

Implement `SolverInfo(name, available, require_milp, executable, message)`, `SolverFactory.catalog()`, and `SolverFactory.create(name, settings)`. Map `cplex` to Pyomo `SolverFactory("cplex")`, `highs` to `SolverFactory("highs")`, and `cbc` to `SolverFactory("cbc")`. Probe availability without solving. Set time limit and MIP gap using each solver's native option names. Raise `SolverUnavailable` when the requested executable is absent; never select `glpk`, `ipopt`, or any LP-only fallback. Normalize termination status, objective, gap, and elapsed seconds into `SolveReport`.

- [ ] **Step 4: Run tests and a solver probe**

Run: `python -m pytest tests/test_solvers.py -q` and `python -c "from common.solvers import SolverFactory; print(SolverFactory.catalog())"`.
Expected: tests pass; unavailable CPLEX/CBC entries are reported as unavailable while HiGHS is used only if it is actually installed.

- [ ] **Step 5: Commit**

```bash
git add common/solvers.py tests/test_solvers.py
git commit -m "feat: add switchable strict MILP solvers"
```

### Task 4: Build the shared diesel microgrid MILP

**Files:**
- Create: `common/milp_model.py`
- Create: `tests/test_milp_model.py`

- [ ] **Step 1: Write structural and fuel-consumption tests**

```python
from common.milp_model import build_dispatch_model
from common.sample_data import default_case


def test_model_has_binary_commitment_and_fuel_segment_variables():
    model = build_dispatch_model(default_case(), default_case().horizons["weekly"])
    assert hasattr(model, "unit_on")
    assert hasattr(model, "fuel_segment_on")
    assert model.T.last() == 167


def test_fuel_curve_is_linked_to_generator_output():
    model = build_dispatch_model(default_case(), default_case().horizons["hourly"])
    assert hasattr(model, "fuel_lph")
    assert hasattr(model, "fuel_curve_power_link")
    assert hasattr(model, "fuel_curve_rate_link")


def test_model_has_power_balance_and_storage_constraints():
    model = build_dispatch_model(default_case(), default_case().horizons["daily"])
    assert hasattr(model, "power_balance")
    assert hasattr(model, "soc_transition")
    assert hasattr(model, "reserve_requirement")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_milp_model.py -q`
Expected: FAIL because the model builder is missing.

- [ ] **Step 3: Implement variables, constraints, and objective**

Create a Pyomo `ConcreteModel` with set `T=range(steps)`, generator set, renewable set, and storage set. Add continuous variables for diesel output, fuel liters per hour, startup/shutdown, renewable dispatch/curtailment, storage charge/discharge/SOC, grid import/export, flexible-load adjustment, reserve, and lost load. Add binary variables for commitment, startup/shutdown, storage charge mode, and fuel-curve segment selection. Enforce power balance, generator bounds, startup/shutdown transitions, minimum up/down time, ramp limits, renewable availability, storage SOC and mutual exclusion, grid limits, flexible-load energy conservation, reserve, and lost-load cap. For each diesel curve, exactly one active segment is selected when the unit is on; convex-combination weights link output power and liters per hour to the configured segment endpoints. Multiply fuel rate by the horizon step hours in the objective and reporting expression. Add baseline-deviation variables when a parent plan is provided. Minimize fuel cost, startup/shutdown cost, imports minus export revenue, storage degradation, curtailment, reserve, lost load, and parent-plan deviation.

- [ ] **Step 4: Run structural tests**

Run: `python -m pytest tests/test_milp_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/milp_model.py tests/test_milp_model.py
git commit -m "feat: build shared diesel microgrid MILP"
```

### Task 5: Implement weekly, daily, and hourly planners

**Files:**
- Create: `common/plan_runner.py`
- Create: `weekly_plan/planner.py`
- Create: `daily_plan/planner.py`
- Create: `hourly_plan/planner.py`
- Create: `tests/test_planners.py`

- [ ] **Step 1: Write horizon and rolling-execution tests**

```python
from common.sample_data import default_case
from weekly_plan.planner import WeeklyPlanner
from daily_plan.planner import DailyPlanner
from hourly_plan.planner import HourlyPlanner


def test_planners_use_required_lengths():
    case = default_case()
    assert WeeklyPlanner(case).horizon.steps == 168
    assert DailyPlanner(case).horizon.steps == 96
    assert HourlyPlanner(case).horizon.steps == 16


def test_hourly_plan_only_executes_first_quarter_hour(fake_solver):
    result = HourlyPlanner(default_case(), solver=fake_solver).run()
    assert len(result.dispatch) == 16
    assert len(result.executed_dispatch) == 1
    assert result.executed_dispatch[0] == result.dispatch[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_planners.py -q`
Expected: FAIL because planner modules are missing.

- [ ] **Step 3: Implement plan runners**

`common/plan_runner.py` must build the model, call the selected MILP solver, normalize results, calculate each diesel generator's fuel liters per interval, total liters, liters by generator, and cumulative fuel curve, and return a `PlanResult`. `WeeklyPlanner` uses the 168-hour horizon and no parent plan. `DailyPlanner` uses the 96-quarter-hour horizon and accepts weekly boundary state and baseline. `HourlyPlanner` uses the 16-quarter-hour horizon, accepts daily baseline and live state, and exposes `executed_dispatch=result.dispatch[:1]`. Reject an unavailable solver before model solve and retain a structured error report.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_planners.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/plan_runner.py weekly_plan daily_plan hourly_plan tests/test_planners.py
git commit -m "feat: add three scheduling horizons"
```

### Task 6: Add SQLite persistence, FastAPI routes, and control actions

**Files:**
- Create: `common/store.py`
- Create: `data/.gitkeep`
- Create: `api/main.py`
- Create: `api/routes.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write API tests**

```python
from fastapi.testclient import TestClient
from api.main import app


client = TestClient(app)


def test_health_and_solver_catalog():
    assert client.get("/api/health").status_code == 200
    payload = client.get("/api/solver").json()
    assert {"cplex", "highs", "cbc"}.issubset(payload["solvers"])


def test_default_case_and_control_state():
    assert client.get("/api/case").status_code == 200
    state = client.get("/api/control").json()
    assert state["auto_hourly_enabled"] is True


def test_hourly_run_requires_milp_solver():
    response = client.post("/api/hourly-plan/solve", json={"solver": "missing-solver"})
    assert response.status_code == 422
    assert "MILP" in response.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -q`
Expected: FAIL because the FastAPI app and store are missing.

- [ ] **Step 3: Implement SQLite persistence and routes**

Create `data/schedule.db` with SQLite tables `diesel_generators`, `fuel_curve_points`, `renewables`, `batteries`, `flexible_loads`, `grid_connections`, `forecasts`, `plans`, `control_state`, and `audit_events`. `common/store.py` must initialize the schema, upsert the complete `CaseData`, load it for calculation, persist every `PlanResult` including diesel summaries, and record control events. Use parameterized SQL and a process lock around writes. Implement `GET /api/health`, `GET/PUT /api/case`, `GET /api/solver`, `POST /api/{weekly,daily,hourly}-plan/solve`, `GET /api/plans/{kind}`, `POST /api/control/{validate,publish,pause,resume,execute,rollback}`, and `GET /api/audit`. Validate solver names and request fields with Pydantic. Return HTTP 422 for unavailable or non-MILP solvers, HTTP 409 for invalid control state, and include plan version, status, objective, MIP gap, elapsed seconds, fuel summary, and interval results in successful responses. Serve `web/index.html` at `/` and static files under `/static`.

- [ ] **Step 4: Run API tests**

Run: `python -m pytest tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/store.py api tests/test_api.py
git commit -m "feat: expose scheduling and control APIs"
```

### Task 7: Build the fixed-viewport, tabbed Web UI

**Files:**
- Create: `web/index.html`
- Create: `web/styles.css`
- Create: `web/app.js`
- Create: `tests/test_web_ui.py`

- [ ] **Step 1: Write static UI checks**

```python
from pathlib import Path


def test_web_ui_has_required_tabs_and_no_scroll_rules():
    html = Path("web/index.html").read_text(encoding="utf-8")
    css = Path("web/styles.css").read_text(encoding="utf-8")
    for label in ["运行总览", "周前计划", "日前计划", "小时滚动", "柴油机与油耗曲线", "求解器与参数", "控制与审计"]:
        assert label in html
    assert "overflow: hidden" in css
    assert "weekly_plan" in html and "daily_plan" in html and "hourly_plan" in html


def test_ui_exposes_fuel_statistics():
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert "柴油消耗曲线" in html
    assert "柴油消耗量" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_ui.py -q`
Expected: FAIL because the web files are missing.

- [ ] **Step 3: Implement the UI**

Create a full-viewport shell with fixed header, tab bar, content panel, and footer status strip. Set `html, body, #app, .shell, .content` to `width:100%; height:100%; overflow:hidden`. Use one active tab at a time. Each tab has compact cards and a local page index with previous/next buttons; do not create any `overflow:auto` or scrollable table. Render SVG line charts for load, renewable output, diesel output, SOC, and fuel liters. The diesel tab includes editable curve-point rows, fuel price, and validation/save controls. The weekly, daily, and hourly tabs show horizon length, solver report, dispatch table page, diesel consumption curve, total liters, and per-generator liters. Solver tab shows CPLEX/HiGHS/CBC availability and selects the solver. Control tab exposes validate, publish, pause/resume auto-hourly, execute current quarter-hour, rollback, and audit records. Use `fetch` to call the API and update a compact status toast; show API errors without changing layout dimensions.

- [ ] **Step 4: Run UI checks and browser verification**

Run: `python -m pytest tests/test_web_ui.py -q`. Start `uvicorn api.main:app --host 0.0.0.0 --port 8000`, open `http://localhost:8000/`, inspect every tab, and verify `document.documentElement.scrollWidth === window.innerWidth` and `document.documentElement.scrollHeight === window.innerHeight`.
Expected: tests pass; every tab fits in the viewport with no horizontal or vertical scrollbar.

- [ ] **Step 5: Commit**

```bash
git add web tests/test_web_ui.py
git commit -m "feat: add fixed viewport scheduling console"
```

### Task 8: Add end-to-end validation and operator documentation

**Files:**
- Create: `tests/test_end_to_end.py`
- Create: `README.md`
- Create: `.gitignore`

- [ ] **Step 1: Write end-to-end assertions**

```python
def test_all_plans_return_fuel_statistics(client):
    for kind in ("weekly", "daily", "hourly"):
        response = client.post(f"/api/{kind}-plan/solve", json={"solver": "highs"})
        assert response.status_code in (200, 422)
        if response.status_code == 200:
            body = response.json()
            assert body["fuel_summary"]["total_liters"] >= 0
            assert len(body["fuel_summary"]["interval_liters"]) == body["horizon_steps"]
```

- [ ] **Step 2: Run the failing integration test**

Run: `python -m pytest tests/test_end_to_end.py -q`
Expected: FAIL until the full API and solver path are connected.

- [ ] **Step 3: Complete documentation and repository hygiene**

Document installation, optional CPLEX setup, HiGHS/CBC fallback selection, sample data format, all endpoints, plan timing, fuel-curve units, and the fact that all three plans require MILP. Add `.gitignore` entries for virtual environments, caches, generated state, logs, and `.superpowers/brainstorm/`.

- [ ] **Step 4: Run the complete verification suite**

Run: `python -m pytest -q`; run `python -m compileall common weekly_plan daily_plan hourly_plan api`; start the API and execute the browser viewport assertions.
Expected: all tests pass, compilation succeeds, and the page remains fixed-size without scrollbars.

- [ ] **Step 5: Commit**

```bash
git add tests/test_end_to_end.py README.md .gitignore
git commit -m "test: validate complete schedule workflow"
```
