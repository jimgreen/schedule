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
