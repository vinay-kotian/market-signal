from datetime import datetime

import pytest

from app.signal_models import SignalAnalysis


def save(client, timestamp, instrument='NIFTY', valid=True):
    return client.app.state.signal_repository.save(SignalAnalysis(
        trigger_id=1, level_id=1, instrument=instrument, level=25000,
        trigger_price=25000, direction='FROM_BELOW', approach_distance=100,
        valid=valid, rejection_reason=None if valid else 'MINIMUM_DISTANCE_NOT_MET',
        timestamp=datetime.fromisoformat(timestamp),
    ))


def test_signal_date_uses_kolkata_midnight(client):
    before = save(client, '2026-09-13T18:29:59+00:00')
    start = save(client, '2026-09-13T18:30:00+00:00')
    end = save(client, '2026-09-14T23:59:59+05:30')
    after = save(client, '2026-09-14T18:30:00+00:00')
    rows = client.get('/signals?signal_date=2026-09-14').json()
    assert [row['id'] for row in rows] == [end.id, start.id]
    assert len(client.get('/signals').json()) == 4
    assert before.id not in [row['id'] for row in rows]
    assert after.id not in [row['id'] for row in rows]


def test_filters_apply_before_recent_limit_and_combine(client):
    target = save(client, '2026-09-14T10:00:00+05:30', 'BANKNIFTY', False)
    save(client, '2026-09-14T10:01:00+05:30', 'BANKNIFTY', True)
    save(client, '2026-09-14T10:02:00+05:30', 'NIFTY', False)
    for _ in range(101):
        save(client, '2026-09-15T10:00:00+05:30')
    assert len(client.get('/signals').json()) == 100
    rows = client.get('/signals?signal_date=2026-09-14&instrument=banknifty&valid=false').json()
    assert [row['id'] for row in rows] == [target.id]
    assert len(client.get('/signals?valid=false').json()) == 2
    assert client.get('/signals?instrument=UNKNOWN').json() == []


@pytest.mark.parametrize('query', ['signal_date=bad', 'valid=maybe', 'instrument='])
def test_invalid_filters(client, query):
    assert client.get('/signals?' + query).status_code == 422
