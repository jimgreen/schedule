from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pyomo.environ import value

from .milp_model import build_dispatch_model
from .schemas import CaseData, FuelSummary, Horizon, HorizonName, PlanResult, SolveReport, SolverSettings
from .solvers import SolverFactory


def _value(variable: Any) -> float:
    raw = value(variable, exception=False)
    return 0.0 if raw is None else float(raw)


class PlanRunner:
    def __init__(self, case: CaseData, horizon: Horizon, solver_name: str = "cplex", solver: Any = None):
        self.case = case
        self.horizon = horizon
        self.solver_name = solver_name
        self.solver = solver
        self.solver_settings = SolverSettings(name=solver_name)

    def run(self, baseline: dict[str, list[float]] | None = None) -> PlanResult:
        model = build_dispatch_model(self.case, self.horizon, baseline=baseline)
        if self.solver is None:
            report = SolverFactory.solve(model, self.solver_settings)
        else:
            report = self.solver.solve(model)
        dispatch = self._extract_dispatch(model)
        executed = dispatch[: self.horizon.execute_steps] if self.horizon.execute_steps else dispatch
        return PlanResult(
            plan_id=f"{self.horizon.name.value}-{uuid.uuid4().hex[:10]}",
            kind=self.horizon.name,
            horizon_steps=self.horizon.steps,
            interval_minutes=self.horizon.interval_minutes,
            status="solved" if report.termination.lower() in {"optimal", "feasible", "locallyoptimal"} else "not_solved",
            dispatch=dispatch,
            executed_dispatch=executed,
            fuel_summary=self._fuel_summary(model),
            solver_report=report,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _extract_dispatch(self, model: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for t in model.T:
            row: dict[str, Any] = {"step": int(t), "generators": {}, "renewables": {}, "batteries": {}}
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
