from __future__ import annotations

from datetime import datetime, timezone
from math import floor
from threading import Lock, RLock
import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from common.sample_data import default_case
from common.schemas import CaseData, ControlEvent, ControlState, DeviceParameters, Forecast, Horizon, HorizonConfig, HorizonName, NetworkModel, OptimizationParameters, PlanRequest, SolverSettings
from common.solvers import SolverFactory, SolverUnavailable
from common.store import ScheduleStore
from common.validation import validate_plan
from common.analytics import energy_summary
from daily_plan.planner import DailyPlanner
from hourly_plan.planner import HourlyPlanner
from weekly_plan.planner import WeeklyPlanner


router = APIRouter(prefix="/api")
store = ScheduleStore()
solve_lock = Lock()
control_lock = RLock()
solve_state_lock = Lock()
solve_state = {
    "running": False,
    "kind": None,
    "started_at": None,
    "finished_at": None,
    "last_status": None,
    "last_plan_id": None,
    "last_error": None,
}


def ensure_case() -> CaseData:
    case = store.load_case()
    if case is None:
        case = default_case()
        store.save_case(case)
    if len(case.horizon_configs) < 3:
        derived: dict[HorizonName, HorizonConfig] = {}
        for name, horizon in ((HorizonName.weekly, Horizon.weekly()), (HorizonName.daily, Horizon.daily()), (HorizonName.hourly, Horizon.hourly())):
            forecast = case.forecast_for(horizon)
            derived[name] = case.horizon_configs.get(name) or HorizonConfig(
                input_interval_minutes=horizon.interval_minutes,
                forecast=Forecast(**forecast, reserve_fraction=case.forecast.reserve_fraction),
                optimization=case.optimization.model_copy(deep=True),
            )
        case.horizon_configs = derived
        for name, config in derived.items():
            store.save_horizon_config(name.value, config)
    return case


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "database": str(store.db_path), "case_loaded": store.case_exists()}


@router.get("/case")
def get_case() -> dict:
    return ensure_case().model_dump(mode="json")


def _module_kind(kind: str) -> HorizonName:
    try:
        return HorizonName(kind)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown module kind") from exc


def _module_config(kind: str) -> HorizonConfig:
    name = _module_kind(kind)
    saved = store.load_horizon_config(kind)
    if saved is not None:
        return saved
    case = ensure_case()
    return case.horizon_configs.get(name) or case.config_for(name)


@router.get("/modules/{kind}/config")
def get_module_config(kind: str):
    name = _module_kind(kind)
    return _module_config(kind).model_dump(mode="json")


@router.put("/modules/{kind}/config")
def put_module_config(kind: str, config: HorizonConfig):
    name = _module_kind(kind)
    expected = {HorizonName.weekly: (60, 168), HorizonName.daily: (15, 96), HorizonName.hourly: (15, 16)}[name]
    if config.input_interval_minutes != expected[0] or len(config.forecast.demand_kw) != expected[1]:
        raise HTTPException(status_code=422, detail=f"{kind} 输入曲线必须为 {expected[0]} 分钟、{expected[1]} 点")
    ensure_case()
    store.save_horizon_config(kind, config)
    _event("module_config_updated", detail=f"{kind} 优化参数和输入曲线已更新", kind=name)
    return config.model_dump(mode="json")


@router.get("/modules/{kind}/audit")
def module_audit(kind: str, limit: int = 100, offset: int = 0, action: str | None = None, query: str | None = None):
    name = _module_kind(kind)
    safe_limit, safe_offset = max(1, min(limit, 500)), max(offset, 0)
    events = store.list_events(safe_limit, kind=name.value, offset=safe_offset, action=action, query=query)
    total = store.count_events(kind=name.value, action=action, query=query)
    return {
        "events": [event.model_dump(mode="json") for event in events],
        "total": total,
        "offset": safe_offset,
        "limit": safe_limit,
        "has_more": safe_offset + len(events) < total,
    }


@router.get("/modules/{kind}/control")
def get_module_control(kind: str):
    _module_kind(kind)
    return store.module_control(kind).model_dump(mode="json")


@router.get("/modules/{kind}/audit/export")
def export_module_audit(kind: str, action: str | None = None, query: str | None = None):
    _module_kind(kind)

    def csv_rows():
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        yield "\ufeff"
        writer.writerow(("action", "plan_id", "detail", "created_at"))
        yield output.getvalue()
        for row in store.iter_event_rows(kind, action=action, query=query):
            output.seek(0)
            output.truncate(0)
            # Treat user-entered text as data when opened in spreadsheet apps.
            writer.writerow("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for v in row)
            yield output.getvalue()

    return StreamingResponse(csv_rows(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{kind}-audit.csv"'
    })


@router.post("/modules/{kind}/control/{action}")
def module_control(kind: str, action: str, plan_id: str | None = None):
    name = _module_kind(kind)
    if action not in {"validate", "publish", "rollback", "execute"}:
        raise HTTPException(status_code=404, detail="unknown module control action")
    with control_lock:
        state = store.module_control(kind)
        if action == 'rollback':
            if not state.previous_published_plan_id:
                raise HTTPException(status_code=409, detail="本模块没有可回退的发布版本")
            state.last_published_plan_id, state.previous_published_plan_id = state.previous_published_plan_id, state.last_published_plan_id
            store.save_module_control(kind, state)
            _event(action, state.last_published_plan_id, '已恢复本模块上次发布版本', name)
            return state.model_dump(mode='json')
        if not plan_id:
            plans = store.list_plan_summaries(kind, limit=1)
            plan_id = plans[0]['plan_id'] if plans else None
        plan = store.get_plan(plan_id) if plan_id else None
        if plan is None:
            raise HTTPException(status_code=409, detail="本模块没有可操作的计划")
        if plan.kind != name:
            raise HTTPException(status_code=409, detail="禁止跨模块操作计划")
        validation = validate_plan(ensure_case(), plan)
        if action != 'validate' and not validation.valid:
            raise HTTPException(status_code=409, detail="计划校核未通过，请查看本模块校核明细")
        if action == 'publish' and state.last_published_plan_id != plan_id:
            state.previous_published_plan_id = state.last_published_plan_id
            state.last_published_plan_id = plan_id
        if action == 'execute':
            if name != HorizonName.hourly or state.last_published_plan_id != plan_id:
                raise HTTPException(status_code=409, detail="仅可执行本模块已发布的小时前计划首个 15 分钟")
            if state.last_executed_plan_id == plan_id:
                return {**state.model_dump(mode='json'), 'already_executed': True}
            state.last_executed_plan_id = plan_id
        store.save_module_control(kind,state)
        detail = '校核通过' if validation.valid else f'校核发现 {len(validation.issues)} 个问题'
        if action == 'execute':
            detail = '已记录首个 15 分钟模拟执行；未连接现场设备'
        _event(action,plan_id,detail,name)
        return {**state.model_dump(mode='json'), 'validation': validation.model_dump(mode='json'),
                'executed_dispatch': plan.dispatch[:1] if action=='execute' else []}


@router.put("/shared/devices")
def put_shared_devices(parameters: DeviceParameters):
    ensure_case()
    store.update_devices(parameters)
    _event("shared_devices_updated", detail="三层计划共用的设备参数已更新")
    return parameters.model_dump(mode="json")


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
    ensure_case()
    store.save_optimization(parameters)
    _event("optimization_updated", detail="优化参数已更新")
    return parameters.model_dump(mode="json")


@router.get("/network-model")
def get_network_model() -> dict:
    return store.load_network_model().model_dump(mode="json")


@router.put("/network-model")
def put_network_model(model: NetworkModel) -> dict:
    ensure_case()
    store.save_network_model(model)
    _event("network_model_updated", detail=f"电网模型已加载：{model.name}")
    return model.model_dump(mode="json")


@router.get("/solver")
def solver_catalog() -> dict:
    return {name: info.__dict__ for name, info in SolverFactory.catalog().items()}


@router.get("/overview")
def overview() -> dict:
    """Return the dashboard data assembled from SQLite, not browser state."""
    latest_plans = {kind: store.list_plans(kind, limit=1) for kind in ("weekly", "daily", "hourly")}
    plans = {kind: values[0] for kind, values in latest_plans.items() if values}
    control_state = store.module_control('hourly')
    latest = max(plans.values(), key=lambda plan: datetime.fromisoformat(plan.created_at)) if plans else None
    return {
        "latest_plan": None if latest is None else latest.model_dump(mode="json"),
        "plans": {kind: plan.model_dump(mode="json") for kind, plan in plans.items()},
        "control": control_state.model_dump(mode="json"),
        "audit_count": store.count_events(),
    }


def _resample_baseline(parent, target_steps: int, target_interval_minutes: int, generator_id: str, offset_minutes: float = 0) -> list[float]:
    source = [float(row.get("generators", {}).get(generator_id, {}).get("power_kw", 0.0)) for row in parent.dispatch]
    if not source:
        return [0.0] * target_steps
    values: list[float] = []
    for target_index in range(target_steps):
        position = (offset_minutes + target_index * target_interval_minutes) / parent.interval_minutes
        lower = min(int(floor(position)), len(source) - 1)
        upper = min(lower + 1, len(source) - 1)
        fraction = position - lower
        values.append(source[lower] + (source[upper] - source[lower]) * fraction)
    return values


def _run_plan(kind: str, request: PlanRequest):
    case = ensure_case()
    planner_type = {"weekly": WeeklyPlanner, "daily": DailyPlanner, "hourly": HourlyPlanner}.get(kind)
    if planner_type is None:
        raise HTTPException(status_code=404, detail=f"unknown plan kind: {kind}")
    module_name = HorizonName(kind)
    module_config = case.config_for(kind)
    solver_name = request.solver or module_config.solver
    baseline = None
    if request.parent_plan_id:
        parent = store.get_plan(request.parent_plan_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="parent plan not found")
        expected_parent = {"daily": "weekly", "hourly": "daily"}.get(kind)
        if expected_parent is None or parent.kind.value != expected_parent:
            raise HTTPException(status_code=409, detail=f"{kind} plan requires a {expected_parent} parent plan")
        target_horizon = case.horizons[kind]
        parent_start = parent.input_snapshot.config_for(parent.kind).start_time if parent.input_snapshot else None
        target_start = module_config.start_time
        if bool(parent_start) != bool(target_start):
            raise HTTPException(status_code=409, detail='上级和本模块必须同时设置计划起点，或都采用相对起点')
        offset_minutes = (target_start-parent_start).total_seconds()/60 if target_start else 0
        if offset_minutes < 0 or offset_minutes + target_horizon.steps*target_horizon.interval_minutes > len(parent.dispatch)*parent.interval_minutes:
            raise HTTPException(status_code=409, detail='上级计划没有覆盖本模块计划时段')
        if parent.status not in {"solved", "feasible"} or len(parent.dispatch) * parent.interval_minutes < target_horizon.steps * target_horizon.interval_minutes:
            raise HTTPException(status_code=409, detail="上级计划没有可用解或覆盖时段不足")
        baseline = {
            generator.id: _resample_baseline(parent, target_horizon.steps, target_horizon.interval_minutes, generator.id, offset_minutes)
            for generator in case.generators
        }
    try:
        planner = planner_type(case, solver_name=solver_name)
        planner.solver_settings = SolverSettings(
            name=solver_name,
            time_limit_seconds=request.time_limit_seconds or module_config.time_limit_seconds,
            mip_gap=request.mip_gap if request.mip_gap is not None else module_config.mip_gap,
        )
        result = planner.run(baseline=baseline, parent_plan_id=request.parent_plan_id)
    except SolverUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _event("solve_failed", detail=str(exc), kind=module_name)
        raise HTTPException(status_code=422, detail=f"MILP solve failed: {exc}") from exc
    store.save_plan(result)
    store.add_event(ControlEvent(action=f"{kind}_solved", plan_id=result.plan_id, detail=result.status, created_at=result.created_at, kind=module_name))
    return result.model_dump(mode="json")


@router.post("/{kind}-plan/solve")
def solve_plan(kind: str, request: PlanRequest):
    _module_kind(kind)
    if not solve_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有优化任务正在运行，请完成后重试")
    started_at = datetime.now(timezone.utc).isoformat()
    with solve_state_lock:
        solve_state.update({"running": True, "kind": kind, "started_at": started_at, "finished_at": None, "last_error": None, "last_status": "running", "last_plan_id": None})
    try:
        result = _run_plan(kind, request)
        with solve_state_lock:
            solve_state.update({"last_status": result.get("status"), "last_plan_id": result.get("plan_id")})
        return result
    except HTTPException as exc:
        with solve_state_lock:
            solve_state.update({"last_status": "error", "last_error": str(exc.detail)})
        raise
    except Exception as exc:
        with solve_state_lock:
            solve_state.update({"last_status": "error", "last_error": str(exc)})
        raise
    finally:
        with solve_state_lock:
            solve_state.update({"running": False, "finished_at": datetime.now(timezone.utc).isoformat()})
        solve_lock.release()


@router.get("/solve-status")
def get_solve_status() -> dict:
    """Expose the single-process solve gate for a responsive operator UI."""
    with solve_state_lock:
        return dict(solve_state)


@router.get("/plans/{kind}")
def list_plans(kind: str, limit: int = 20):
    if kind not in {"weekly", "daily", "hourly"}:
        raise HTTPException(status_code=404, detail="unknown plan kind")
    return {"plans": [plan.model_dump(mode="json") for plan in store.list_plans(kind, limit=max(1, min(limit, 100)))]}


@router.get("/plans/{kind}/compare")
def compare_plans(kind: str, left_id: str, right_id: str):
    """Compare two versions without returning their large dispatch payloads."""
    if kind not in {"weekly", "daily", "hourly"}:
        raise HTTPException(status_code=404, detail="unknown plan kind")
    left, right = store.get_plan(left_id), store.get_plan(right_id)
    if left is None or right is None:
        raise HTTPException(status_code=404, detail="plan not found")
    if left.kind.value != kind or right.kind.value != kind:
        raise HTTPException(status_code=409, detail="只能比较同一调度模块的计划")

    def compact(plan):
        return {
            "plan_id": plan.plan_id,
            "status": plan.status,
            "created_at": plan.created_at,
            "solver": plan.solver_report.solver,
            "objective": plan.solver_report.objective,
            "mip_gap": plan.solver_report.mip_gap,
            "elapsed_seconds": plan.solver_report.elapsed_seconds,
            "total_liters": plan.fuel_summary.total_liters,
            "energy_summary": plan.energy_summary or energy_summary(plan.dispatch, plan.interval_minutes),
            "cost_breakdown": plan.cost_breakdown,
            "performance": plan.performance,
        }

    left_data, right_data = compact(left), compact(right)
    numeric_keys = ("objective", "total_liters", "elapsed_seconds")
    delta = {key: None if left_data[key] is None or right_data[key] is None else round(right_data[key] - left_data[key], 6) for key in numeric_keys}
    if left.status not in {'solved','feasible'} or right.status not in {'solved','feasible'}:
        raise HTTPException(status_code=409, detail="无可用解的版本不能参与数值比较")
    left_start = left.input_snapshot.config_for(kind).start_time if left.input_snapshot else None
    right_start = right.input_snapshot.config_for(kind).start_time if right.input_snapshot else None
    return {"left": left_data, "right": right_data, "delta_right_minus_left": delta, "same_start_time": left_start == right_start}


@router.get("/plan-summaries")
def plan_summaries(kind: str | None = None, limit: int = 50, offset: int = 0, status: str | None = None):
    if kind is not None and kind not in {"weekly", "daily", "hourly"}:
        raise HTTPException(status_code=404, detail="unknown plan kind")
    if status is not None and status not in {"solved", "feasible", "not_solved"}:
        raise HTTPException(status_code=422, detail="unknown plan status")
    safe_limit, safe_offset = max(1, min(limit, 200)), max(offset, 0)
    plans = store.list_plan_summaries(kind, limit=safe_limit, offset=safe_offset, status=status)
    total = store.count_plans(kind, status=status)
    return {"plans": plans, "total": total, "offset": safe_offset, "limit": safe_limit, "has_more": safe_offset + len(plans) < total}


@router.get("/plans/id/{plan_id}")
def get_plan(plan_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    if not plan.energy_summary and plan.dispatch:
        plan.energy_summary = energy_summary(plan.dispatch, plan.interval_minutes)
    return plan.model_dump(mode="json")


@router.post("/plans/id/{plan_id}/validate")
def validate_stored_plan(plan_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    report = validate_plan(ensure_case(), plan)
    _event("plan_validated", plan_id=plan_id, detail="校核通过" if report.valid else f"校核发现 {len(report.issues)} 个问题", kind=plan.kind)
    return report.model_dump(mode="json")


@router.get("/control")
def get_control(kind: str = 'hourly') -> dict:
    return get_module_control(kind)


def _event(action: str, plan_id: str | None = None, detail: str = "", kind: HorizonName | None = None) -> None:
    store.add_event(ControlEvent(action=action, plan_id=plan_id, detail=detail, created_at=datetime.now(timezone.utc).isoformat(), kind=kind))


@router.post("/control/{action}")
def control(action: str, plan_id: str | None = None, kind: str = 'hourly'):
    # Legacy clients use the same module gates; never publish a global latest plan.
    if action in {'pause','resume'}:
        raise HTTPException(status_code=409, detail='尚未接入自动触发器；当前通过各模块手动计算')
    return module_control(kind, action, plan_id)


@router.get("/audit")
def audit(limit: int = 100, offset: int = 0, kind: str | None = None, action: str | None = None, query: str | None = None):
    if kind is not None and kind not in {"weekly", "daily", "hourly"}:
        raise HTTPException(status_code=404, detail="unknown module kind")
    safe_limit, safe_offset = max(1, min(limit, 500)), max(offset, 0)
    events = store.list_events(safe_limit, kind=kind, offset=safe_offset, action=action, query=query)
    total = store.count_events(kind=kind, action=action, query=query)
    return {
        "events": [event.model_dump(mode="json") for event in events],
        "total": total,
        "offset": safe_offset,
        "limit": safe_limit,
        "has_more": safe_offset + len(events) < total,
    }
