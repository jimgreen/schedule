"""Keep all API tests away from the runtime database, regardless of environment."""
import os
import tempfile
from pathlib import Path

import pytest

_database_directory = tempfile.TemporaryDirectory(prefix='schedule-pytest-')
os.environ['SCHEDULE_DB_PATH'] = str(Path(_database_directory.name) / 'bootstrap.db')


@pytest.fixture(autouse=True)
def isolate_api_database(tmp_path, monkeypatch):
    from api import routes
    from common.store import ScheduleStore
    monkeypatch.setattr(routes, 'store', ScheduleStore(tmp_path / 'schedule.db'))
