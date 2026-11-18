from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any
from math import isfinite
from time import perf_counter

from pyomo.environ import value, Var, Constraint
from .analytics import energy_summary

from .milp_model import build_dispatch_model
from .schemas import CaseData, FuelSummary, Horizon, HorizonName, PlanResult, SolveReport, SolverSettings
from .solvers import SolverFactory


def _value(variable: Any) -> float:
    raw = value(variable, exception=False)
    if raw is None or not isfinite(float(raw)):
        raise ValueError("求解器未返回完整有限数值解")
    return float(raw)


class PlanRunner:
    def __init__(self, case: CaseData, horizon: Horizon, solver_name: str = "cplex", solver: Any = None):
        self.case = case
        self.horizon = horizon
        self.solver_name = solver_name
        self.solver = solver
        self.solver_settings = SolverSettings(name=solver_name)

    def run(self, baseline: dict[str, list[float]] | None = None, parent_plan_id: str | None = None) -> PlanResult:
        started = perf_counter()
        model = build_dispatch_model(self.case, self.horizon, baseline=baseline)
        built = perf_counter()
        if self.solver is None:
            report = SolverFactory.solve(model, self.solver_settings)
        else:
            report = self.solver.solve(model)
        usable = report.has_solution or (self.solver is not None and report.termination.lower() in {'optimal', 'feasible'})
        solved = perf_counter()
        dispatch = self._extract_dispatch(model) if usable else []
        costs = {key: round(_value(term), 8) for key, term in model.cost_terms.items()} if usable else {}
        fuel = self._fuel_summary(model) if usable else FuelSummary(total_liters=0, interval_liters=[], by_generator_liters={}, cumulative_liters=[])
        variables = list(model.component_data_objects(Var))
        performance = {
            'build_seconds': round(built-started, 6),
            'solve_seconds': round(solved-built, 6),
            'extract_seconds': round(perf_counter()-solved, 6),
            'total_seconds': round(perf_counter()-started, 6),
            'variables': len(variables), 'binary_variables': sum(v.is_binary() for v in variables),
            'constraints': sum(1 for _ in model.component_data_objects(Constraint)),
        }
        executed = dispatch[: self.horizon.execute_steps] if self.horizon.execute_steps else dispatch
        return PlanResult(
            plan_id=f"{self.horizon.name.value}-{uuid.uuid4().hex[:10]}",
            kind=self.horizon.name,
            horizon_steps=self.horizon.steps,
            interval_minutes=self.horizon.interval_minutes,
            status=("solved" if report.termination.lower() == 'optimal' else 'feasible') if usable else "not_solved",
            dispatch=dispatch,
            executed_dispatch=executed,
            fuel_summary=fuel,
            solver_report=report,
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_plan_id=parent_plan_id,
            input_snapshot=self.case.model_copy(deep=True),
            energy_summary=energy_summary(dispatch, self.horizon.interval_minutes) if usable else {},
            cost_breakdown=costs,
            performance=performance,
        )

    def _extract_dispatch(self, model: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for t in model.T:
            row: dict[str, Any] = {"step": int(t), "generators": {}, "renewables": {}, "batteries": {}}
            start = self.case.config_for(self.horizon).start_time
            if start:
                row['timestamp'] = (start+timedelta(minutes=int(t)*self.horizon.interval_minutes)).isoformat()
            for gen in self.case.generators:
                row["generators"][gen.id] = {
                    "power_kw": round(_value(model.power[gen.id, t]), 4),
                    "on": round(_value(model.unit_on[gen.id, t])),
                    "fuel_lph": round(_value(model.fuel_lph[gen.id, t]), 4),
                }
            for renewable in self.case.renewables:
                row["renewables"][renewable.id] = round(_value(model.renewable_dispatch[renewable.id, t]), 4)
            for battery in self.case.batteries:
                row["batteries"][battery.id] = {
                    "charge_kw": round(_value(model.charge[battery.id, t]), 4),
                    "discharge_kw": round(_value(model.discharge[battery.id, t]), 4),
                    "soc_kwh": round(_value(model.soc[battery.id, t]), 4),
                }
            row.update({
                "grid_import_kw": round(_value(model.grid_import[t]), 4),
                "grid_export_kw": round(_value(model.grid_export[t]), 4),
                "reserve_kw": round(_value(model.reserve[t]), 4),
                "lost_load_kw": round(_value(model.lost_load[t]), 4),
                "demand_kw": round(model._forecast["demand_kw"][int(t)], 4),
                "wind_available_kw": round(model._forecast["wind_kw"][int(t)], 4),
                "pv_available_kw": round(model._forecast["pv_kw"][int(t)], 4),
                "flexible_load_kw": round(sum(_value(model.flex_power[f.id, t]) for f in self.case.flexible_loads), 4),
                "renewable_curtailment_kw": round(sum(_value(model.renewable_curtailment[r.id, t]) for r in self.case.renewables), 4),
                "reserve_required_kw": round(model._forecast["demand_kw"][int(t)] * self.case.config_for(self.horizon).forecast.reserve_fraction, 4),
                "flexible_loads": {f.id: round(_value(model.flex_power[f.id,t]),4) for f in self.case.flexible_loads},
            })
            rows.append(row)
        return rows

    def _fuel_summary(self, model: Any) -> FuelSummary:
        interval: list[float] = []
        by_generator = {gen.id: 0.0 for gen in self.case.generators}
        for t in model.T:
            total = 0.0
            for gen in self.case.generators:
                liters = _value(model.fuel_lph[gen.id, t]) * self.horizon.step_hours
                by_generator[gen.id] += liters
                total += liters
            interval.append(round(total, 4))
        cumulative: list[float] = []
        running = 0.0
        for liters in interval:
            running += liters
            cumulative.append(round(running, 4))
        return FuelSummary(
            total_liters=round(sum(interval), 4),
            interval_liters=interval,
            by_generator_liters={key: round(val, 4) for key, val in by_generator.items()},
            cumulative_liters=cumulative,
        )
