from common.schemas import SolveReport
from common.sample_data import default_case
from daily_plan.planner import DailyPlanner
from hourly_plan.planner import HourlyPlanner
from weekly_plan.planner import WeeklyPlanner


class FakeSolver:
    def solve(self, model):
        for g in model.G:
            for t in model.T:
                model.unit_on[g, t].value = 1
                model.startup[g, t].value = 0
                model.shutdown[g, t].value = 0
                model.power[g, t].value = 0
                model.fuel_lph[g, t].value = 0
        for t in model.T:
            model.grid_import[t].value = 0
            model.grid_export[t].value = 0
            model.reserve[t].value = 0
            model.lost_load[t].value = 0
        for f in model.F:
            for t in model.T:
                model.flex_power[f,t].value = 0
        for r in model.R:
            for t in model.T:
                model.renewable_dispatch[r, t].value = 0
                model.renewable_curtailment[r, t].value = model._forecast["wind_kw" if r == "wind" else "pv_kw"][int(t)]
        for b in model.B:
            for t in model.T:
                model.charge[b, t].value = 0
                model.discharge[b, t].value = 0
                model.soc[b, t].value = 0
        return SolveReport(solver="fake", status="ok", termination="optimal", objective=0, elapsed_seconds=0)


def test_planners_use_required_lengths():
    case = default_case()
    assert WeeklyPlanner(case).horizon.steps == 168
    assert DailyPlanner(case).horizon.steps == 96
    assert HourlyPlanner(case).horizon.steps == 16


def test_hourly_plan_only_executes_first_quarter_hour():
    result = HourlyPlanner(default_case(), solver=FakeSolver()).run()
    assert len(result.dispatch) == 16
    assert len(result.executed_dispatch) == 1
    assert result.executed_dispatch[0] == result.dispatch[0]
