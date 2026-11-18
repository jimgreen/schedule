from __future__ import annotations

import time
import importlib.util
import shutil
import math
from dataclasses import dataclass
from typing import Any

from pyomo.environ import SolverFactory as PyomoSolverFactory

from .schemas import SolveReport, SolverSettings


class SolverUnavailable(RuntimeError):
    """Raised when the requested MILP executable is not installed."""


@dataclass(frozen=True)
class SolverInfo:
    name: str
    available: bool
    require_milp: bool = True
    executable: str | None = None
    message: str = ""


class SolverFactory:
    _names = ("cplex", "highs", "cbc")

    @classmethod
    def catalog(cls) -> dict[str, SolverInfo]:
        result: dict[str, SolverInfo] = {}
        for name in cls._names:
            available, executable, message = cls._probe(name)
            result[name] = SolverInfo(name=name, available=available, executable=executable, message=message)
        return result

    @classmethod
    def _probe(cls, name: str) -> tuple[bool, str | None, str]:
        """Probe without launching a solver subprocess.

        Pyomo's generic executable probe can block for a missing CPLEX binary,
        so the catalog uses import/module and PATH checks first.
        """
        if name == "cplex":
            if importlib.util.find_spec("cplex") is not None:
                return True, "python:cplex", "CPLEX Python API available"
            executable = shutil.which("cplex")
            return bool(executable), executable, "CPLEX executable available" if executable else "CPLEX is not installed"
        if name == "highs":
            if importlib.util.find_spec("highspy") is not None:
                return True, "python:highspy", "HiGHS Python API available"
            executable = shutil.which("highs")
            return bool(executable), executable, "HiGHS executable available" if executable else "HiGHS is not installed"
        executable = shutil.which("cbc")
        return bool(executable), executable, "CBC executable available" if executable else "CBC is not installed"

    @classmethod
    def create(cls, name: str, settings: SolverSettings | None = None) -> Any:
        settings = settings or SolverSettings(name=name)
        normalized = name.lower().strip()
        if normalized not in cls._names:
            raise SolverUnavailable(f"Unknown solver '{name}'. A MILP solver is required; no LP fallback is used.")
        available, executable, message = cls._probe(normalized)
        if not available:
            raise SolverUnavailable(f"MILP solver '{normalized}' is not installed or not executable.")
        solver_name = normalized
        if normalized == "cplex" and importlib.util.find_spec("cplex") is not None:
            solver_name = "cplex_direct"
        try:
            solver = PyomoSolverFactory(solver_name)
        except Exception as exc:
            raise SolverUnavailable(f"MILP solver '{normalized}' cannot be loaded: {exc}") from exc

        if normalized == "cplex":
            solver.options["timelimit"] = settings.time_limit_seconds
            solver.options["mipgap"] = settings.mip_gap
        elif normalized == "highs":
            solver.options["time_limit"] = settings.time_limit_seconds
            solver.options["mip_rel_gap"] = settings.mip_gap
        elif normalized == "cbc":
            solver.options["seconds"] = settings.time_limit_seconds
            solver.options["ratio"] = settings.mip_gap
        return solver

    @classmethod
    def solve(cls, model: Any, settings: SolverSettings) -> SolveReport:
        solver = cls.create(settings.name, settings)
        started = time.perf_counter()
        result = solver.solve(model, tee=False, load_solutions=False)
        has_solution = len(result.solution) > 0
        if has_solution:
            model.solutions.load_from(result)
        elapsed = time.perf_counter() - started
        status = str(result.solver.status)
        termination = str(result.solver.termination_condition)
        objective = None
        try:
            from pyomo.environ import value

            objective = float(value(model.objective, exception=False)) if has_solution else None
        except Exception:
            objective = None
        gap = None
        for attr in ("mip_gap", "gap"):
            raw = getattr(result.solver, attr, None)
            if raw is not None:
                try:
                    gap = float(raw)
                except (TypeError, ValueError):
                    pass
                break
        if gap is not None and not math.isfinite(gap):
            gap = None
        if gap is None and has_solution and termination.lower() == 'optimal':
            gap = 0.0
        return SolveReport(
            solver=settings.name,
            status=status,
            termination=termination,
            objective=objective,
            mip_gap=gap,
            elapsed_seconds=round(elapsed, 6),
            message=f"{settings.name} returned {termination}",
            has_solution=has_solution,
        )
