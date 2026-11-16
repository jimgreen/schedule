from common.plan_runner import PlanRunner
from common.schemas import CaseData, Horizon


class WeeklyPlanner(PlanRunner):
    def __init__(self, case: CaseData, solver_name: str = "cplex", solver=None):
        super().__init__(case, Horizon.weekly(), solver_name=solver_name, solver=solver)
