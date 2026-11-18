import csv
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import routes
from api.main import app
from common.schemas import ControlEvent


def test_history_filter_totals_and_last_partial_page():
    client = TestClient(app)
    plan = client.post('/api/hourly-plan/solve', json={'solver':'highs'}).json()
    from common.schemas import PlanResult
    for i in range(8):
        item = PlanResult.model_validate(plan)
        item.plan_id = f'copy-{i}'
        item.status = 'not_solved' if i < 2 else 'solved'
        routes.store.save_plan(item)
    result = client.get('/api/plan-summaries?kind=hourly&status=solved&limit=6').json()
    assert result['total'] == 7 and result['has_more']
    assert len(result['plans']) == 6
    last = client.get('/api/plan-summaries?kind=hourly&status=solved&limit=6&offset=6').json()
    assert len(last['plans']) == 1 and not last['has_more']
    assert client.get('/api/plan-summaries?status=bad').status_code == 422
    assert client.get('/api/plan-summaries?kind=daily').json()['total'] == 0


def test_audit_filters_export_all_pages_and_scope():
    client = TestClient(app)
    for kind in ['hourly','daily']:
        for i in range(9):
            routes.store.add_event(ControlEvent(kind=kind, action='publish' if i<8 else 'validate',
                plan_id=f'{kind}-{i}', detail='=测试,\n记录', created_at=f'2026-11-18T00:00:0{i}+00:00'))
    result = client.get('/api/modules/hourly/audit?limit=3&action=publish&query=记录').json()
    assert result['total'] == 8 and result['has_more'] and len(result['events']) == 3
    tail = client.get('/api/modules/hourly/audit?limit=3&offset=6&action=publish&query=记录').json()
    assert len(tail['events']) == 2 and not tail['has_more']
    exported = client.get('/api/modules/hourly/audit/export?action=publish&query=记录')
    rows = list(csv.reader(io.StringIO(exported.content.decode('utf-8-sig'))))
    assert len(rows) == 9
    assert all(row[1].startswith('hourly-') for row in rows[1:])
    assert rows[1][2] == "'=测试,\n记录"
    assert client.get('/api/modules/invalid/audit/export').status_code == 404


def test_solve_status_tracks_running_conflict_and_failure(monkeypatch):
    started, release = Event(), Event()

    def slow_run(kind, request):
        started.set()
        assert release.wait(5)
        raise HTTPException(status_code=422, detail='test solve failure')

    monkeypatch.setattr(routes, '_run_plan', slow_run)
    client = TestClient(app)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, '/api/hourly-plan/solve', json={})
        try:
            assert started.wait(5)
            state = client.get('/api/solve-status').json()
            assert state['running'] and state['kind'] == 'hourly'
            assert state['last_plan_id'] is None and state['finished_at'] is None
            assert client.post('/api/daily-plan/solve', json={}).status_code == 409
        finally:
            release.set()
        assert future.result().status_code == 422
    state = client.get('/api/solve-status').json()
    assert not state['running'] and state['last_status'] == 'error'
    assert state['last_error'] == 'test solve failure' and state['finished_at']
