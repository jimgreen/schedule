import pytest
from fastapi.testclient import TestClient
from pyomo.environ import value

from api import routes
from api.main import app
from common.milp_model import build_dispatch_model
from common.sample_data import default_case
from common.schemas import Horizon, HorizonName, SolverSettings
from common.solvers import SolverFactory
from common.store import ScheduleStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, 'store', ScheduleStore(tmp_path / 'schedule.db'))
    return TestClient(app)


def test_three_modules_save_independent_settings_curves_and_audit(client):
    configs = {k: client.get(f'/api/modules/{k}/config').json() for k in ('weekly', 'daily', 'hourly')}
    for kind, steps in [('weekly', 168), ('daily', 96), ('hourly', 16)]:
        assert len(configs[kind]['forecast']['demand_kw']) == steps
    edited = configs['daily']
    edited['optimization']['fuel_cost_multiplier'] = 2.5
    edited['forecast']['demand_kw'][70] = 777
    edited['solver'] = 'highs'
    assert client.put('/api/modules/daily/config', json=edited).status_code == 200
    assert client.get('/api/modules/daily/config').json() == edited
    for kind in ('weekly', 'hourly'):
        assert client.get(f'/api/modules/{kind}/config').json() == configs[kind]
        assert client.get(f'/api/modules/{kind}/audit').json()['events'] == []
    assert len(client.get('/api/modules/daily/audit').json()['events']) == 1
    assert client.get('/api/modules/bad/config').status_code == 404


def test_reject_wrong_interval_and_short_forecast(client):
    config = client.get('/api/modules/daily/config').json()
    config['input_interval_minutes'] = 60
    assert client.put('/api/modules/daily/config', json=config).status_code == 422
    config['input_interval_minutes'] = 15
    for key in ('demand_kw', 'wind_kw', 'pv_kw'):
        config['forecast'][key].pop()
    assert client.put('/api/modules/daily/config', json=config).status_code == 422


def test_fuel_curve_supports_interior_breakpoints_and_interpolation():
    case = default_case()
    case.generators = case.generators[:1]
    case.generators[0].initial_power_kw = 260
    case.generators[0].initial_up_steps = 10
    case.forecast.reserve_fraction = 0
    model = build_dispatch_model(case, Horizon(name=HorizonName.hourly, steps=1, interval_minutes=15))
    model.power['dg1', 0].fix(260)
    report = SolverFactory.solve(model, SolverSettings(name='highs'))
    assert report.termination.lower() == 'optimal'
    assert value(model.fuel_lph['dg1', 0]) == pytest.approx(54)


def test_shared_device_save_does_not_reset_module_config(client):
    edited = client.get('/api/modules/hourly/config').json()
    edited['forecast']['demand_kw'][0] = 601
    client.put('/api/modules/hourly/config', json=edited)
    case = client.get('/api/case').json()
    case['generators'][0]['fuel_price_per_liter'] = 8.2
    response = client.put('/api/shared/devices', json={k: case[k] for k in ('generators', 'renewables', 'batteries', 'flexible_loads', 'grid', 'fuel_price_per_liter')})
    assert response.status_code == 200
    assert client.get('/api/modules/hourly/config').json() == edited
    assert client.get('/api/case').json()['generators'][0]['fuel_price_per_liter'] == 8.2


def test_solver_uses_module_inputs_and_controls_cannot_cross_modules(client):
    config=client.get('/api/modules/hourly/config').json()
    config['solver']='highs'
    config['forecast']['demand_kw']=[480]*16
    client.put('/api/modules/hourly/config',json=config)
    response=client.post('/api/hourly-plan/solve',json={})
    assert response.status_code==200, response.text
    plan=response.json()
    assert plan['solver_report']['solver']=='highs'
    assert plan['dispatch'][0]['demand_kw']==480
    plan_id=plan['plan_id']
    report=client.post(f'/api/modules/hourly/control/validate?plan_id={plan_id}').json()['validation']
    assert report['valid'], report['issues']
    assert client.post(f'/api/modules/daily/control/publish?plan_id={plan_id}').status_code==409
    assert client.post(f'/api/modules/hourly/control/execute?plan_id={plan_id}').status_code==409
    assert client.post(f'/api/modules/hourly/control/publish?plan_id={plan_id}').status_code==200
    assert client.get('/api/modules/weekly/control').json()['last_published_plan_id'] is None
    executed=client.post(f'/api/modules/hourly/control/execute?plan_id={plan_id}').json()
    assert len(executed['executed_dispatch'])==1
    assert client.post(f'/api/modules/hourly/control/execute?plan_id={plan_id}').json()['already_executed']
    # Updating inputs later cannot invalidate the captured inputs of an old version.
    config['forecast']['demand_kw']=[600]*16
    client.put('/api/modules/hourly/config',json=config)
    assert client.post(f'/api/modules/hourly/control/validate?plan_id={plan_id}').json()['validation']['valid']
    tampered=routes.store.get_plan(plan_id)
    tampered.dispatch[0]['batteries']['bat1']['soc_kwh']=599
    routes.store.save_plan(tampered)
    invalid=client.post(f'/api/modules/hourly/control/validate?plan_id={plan_id}').json()['validation']
    assert not invalid['valid']
    assert any(issue['code']=='soc_balance' for issue in invalid['issues'])


def test_summary_query_does_not_read_payload(client):
    statements=[]
    original=routes.store._connect
    from contextlib import contextmanager
    @contextmanager
    def traced():
        with original() as conn:
            conn.set_trace_callback(statements.append)
            yield conn
    routes.store._connect=traced
    client.get('/api/plan-summaries?kind=weekly')
    assert not any('payload' in s.lower() for s in statements)


def test_infeasible_solve_never_returns_fake_dispatch(client):
    config=client.get('/api/modules/hourly/config').json()
    config['solver']='highs'
    config['forecast']['reserve_fraction']=1
    config['forecast']['demand_kw']=[10000]*16
    client.put('/api/modules/hourly/config',json=config)
    response=client.post('/api/hourly-plan/solve',json={})
    assert response.status_code==200
    plan=response.json()
    assert plan['status']=='not_solved'
    assert plan['dispatch']==[] and plan['executed_dispatch']==[]
    assert client.post(f"/api/modules/hourly/control/publish?plan_id={plan['plan_id']}").status_code==409


def test_legacy_data_migrates_to_three_independent_configs(client):
    case=default_case()
    case.horizon_configs={}
    case.optimization.fuel_cost_multiplier=3
    routes.store.save_case(case)
    configs={kind:client.get(f'/api/modules/{kind}/config').json() for kind in ('weekly','daily','hourly')}
    assert all(c['optimization']['fuel_cost_multiplier']==3 for c in configs.values())
    assert [len(configs[k]['forecast']['demand_kw']) for k in configs]==[168,96,16]
    # Reopen SQLite to prove persistence beyond the API's Python objects.
    reopened=ScheduleStore(routes.store.db_path)
    assert len(reopened.load_case().horizon_configs)==3
