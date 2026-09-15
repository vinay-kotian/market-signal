import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(autouse=True)
def default_trading_clock(monkeypatch):
    # Existing scenario tests must not depend on the actual time of day.
    monkeypatch.setattr('app.main.utc_now', lambda: datetime(2026, 9, 14, 4, 30, tzinfo=timezone.utc))


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "test.sqlite3")) as client:
        yield client
