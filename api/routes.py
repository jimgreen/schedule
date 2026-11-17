from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from common.sample_data import default_case
from common.schemas import CaseData, ControlEvent, ControlState, NetworkModel, OptimizationParameters, PlanRequest
from common.solvers import SolverFactory, SolverUnavailable
from common.store import ScheduleStore
from daily_plan.planner import DailyPlanner
from hourly_plan.planner import HourlyPlanner
from weekly_plan.planner import WeeklyPlanner


router = APIRouter(prefix="/api")
store = ScheduleStore()


def ensure_case() -> CaseData:
    case = store.load_case()
    if case is None:
        case = default_case()
        store.save_case(case)
    return case


@router.get("/health")
def health() -> dict:
    case = store.load_case()
    return {"status": "ok", "database": str(store.db_path), "case_loaded": case is not None}


@router.get("/case")
def get_case() -> dict:
    return ensure_case().model_dump(mode="json")


@router.put("/case")
def put_case(case: CaseData) -> dict:
    store.save_case(case)
    store.add_event(ControlEvent(action="case_updated", detail="资产、油耗曲线或预测已更新", created_at=datetime.now(timezone.utc).isoformat()))
    return case.model_dump(mode="json")


@router.get("/optimization-params")
def get_optimization_params() -> dict:
    return store.load_optimization().model_dump(mode="json")


@router.put("/optimization-params")
def put_optimization_params(parameters: OptimizationParameters) -> dict:
    store.save_optimization(parameters)
    case = ensure_case()
    case.optimization = parameters
    store.save_case(case)
    _event("optimization_updated", detail="优化参数已更新")
    return parameters.model_dump(mode="json")


@router.get("/network-model")
def get_network_model() -> dict:
    return store.load_network_model().model_dump(mode="json")


@router.put("/network-model")
def put_network_model(model: NetworkModel) -> dict:
    store.save_network_model(model)
    case = ensure_case()
    case.network_model = model
    store.save_case(case)
    _event("network_model_updated", detail=f"电网模型已加载：{model.name}")
    return model.model_dump(mode="json")


@router.get("/solver")
def solver_catalog() -> dict:
    return {name: info.__dict__ for name, info in SolverFactory.catalog().items()}


@router.get("/overview")
def overview() -> dict:
    """Return the dashboard data assembled from SQLite, not browser state."""
    plans = {kind: store.list_plans(kind, limit=1)[0] for kind in ("weekly", "daily", "hourly") if store.list_plans(kind, limit=1)}
    control_state = store.control_state()
    latest = max(plans.values(), key=lambda plan: plan.created_at) if plans else None
    return {
        "latest_plan": None if latest is None else latest.model_dump(mode="json"),
        "plans": {kind: plan.model_dump(mode="json") for kind, plan in plans.items()},
        "control": control_state.model_dump(mode="json"),
        "audit_count": len(store.list_events(500)),
    }


def _run_plan(kind: str, request: PlanRequest):
    case = ensure_case()
    planner_type = {"weekly": WeeklyPlanner, "daily": DailyPlanner, "hourly": HourlyPlanner}.get(kind)
    if planner_type is None:
        raise HTTPException(status_code=404, detail=f"unknown plan kind: {kind}")
    try:
        planner = planner_type(case, solver_name=request.solver)
        if request.time_limit_seconds is not None or request.mip_gap is not None:
            from common.schemas import SolverSettings

            planner.solver_settings = SolverSettings(
                name=request.solver,
                time_limit_seconds=request.time_limit_seconds or 30.0,
                mip_gap=request.mip_gap if request.mip_gap is not None else 0.01,
            )
        result = planner.run()
    except SolverUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"MILP solve failed: {exc}") from exc
    store.save_plan(result)
    store.add_event(ControlEvent(action=f"{kind}_solved", plan_id=result.plan_id, detail=result.status, created_at=result.created_at))
    return result.model_dump(mode="json")


@router.post("/{kind}-plan/solve")
def solve_plan(kind: str, request: PlanRequest):
    return _run_plan(kind, request)


@router.get("/plans/{kind}")
def list_plans(kind: str, limit: int = 20):
    if kind not in {"weekly", "daily", "hourly"}:
        raise HTTPException(status_code=404, detail="unknown plan kind")
    return {"plans": [plan.model_dump(mode="json") for plan in store.list_plans(kind, limit=max(1, min(limit, 100)))]}


@router.get("/plans/id/{plan_id}")
def get_plan(plan_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan.model_dump(mode="json")


@router.get("/control")
def get_control() -> dict:
    return store.control_state().model_dump(mode="json")


def _event(action: str, plan_id: str | None = None, detail: str = "") -> None:
    store.add_event(ControlEvent(action=action, plan_id=plan_id, detail=detail, created_at=datetime.now(timezone.utc).isoformat()))


@router.post("/control/{action}")
def control(action: str, plan_id: str | None = None):
    if action not in {"validate", "publish", "pause", "resume", "execute", "rollback"}:
        raise HTTPException(status_code=404, detail="unknown control action")
    state = store.control_state()
    if action in {"validate", "publish", "execute", "rollback"} and not plan_id:
        latest = store.list_plans(limit=1)
        plan_id = latest[0].plan_id if latest else None
    if action in {"validate", "publish", "execute", "rollback"} and plan_id:
        plan = store.get_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="plan not found")
    if action == "pause":
        state.auto_hourly_enabled = False
    elif action == "resume":
        state.auto_hourly_enabled = True
    elif action == "publish":
        if not plan_id:
            raise HTTPException(status_code=409, detail="plan_id is required to publish")
        state.last_published_plan_id = plan_id
    elif action == "execute":
        if not plan_id:
            raise HTTPException(status_code=409, detail="plan_id is required to execute")
        state.last_executed_plan_id = plan_id
    elif action == "rollback":
        state.last_published_plan_id = None
    store.update_control(state)
    _event(action, plan_id, "control action completed")
    return state.model_dump(mode="json")


@router.get("/audit")
def audit(limit: int = 100):
    return {"events": [event.model_dump(mode="json") for event in store.list_events(max(1, min(limit, 500)))]}
