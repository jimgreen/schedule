from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from common.sample_data import default_case
from common.schemas import CaseData, ControlEvent, ControlState, PlanRequest
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


@router.get("/solver")
def solver_catalog() -> dict:
    return {name: info.__dict__ for name, info in SolverFactory.catalog().items()}


def _run_plan(kind: str, request: PlanRequest):
    case = ensure_case()
    planner_type = {"weekly": WeeklyPlanner, "daily": DailyPlanner, "hourly": HourlyPlanner}.get(kind)
    if planner_type is None:
        raise HTTPException(status_code=404, detail=f"unknown plan kind: {kind}")
    try:
        planner = planner_type(case, solver_name=request.solver)
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
