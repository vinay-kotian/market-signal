from active_level_fixture import create_active_level, create_active_record
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.database import initialize_database, connect
from app.main import create_app
from app.option_prices import SimulatedOptionPrices
from app.settings import SignalSettings, TradeSettings


def level(client, price=25000):
    return create_active_level(client, json=dict(instrument='NIFTY', price=price, enabled=True)).json()['id']


def ticks(client, *prices, instrument='NIFTY'):
    for price in prices:
        assert client.post('/simulation/tick', json=dict(instrument=instrument, price=price)).status_code == 200


def state(client, id):
    return client.get(f'/levels/{id}').json()['status']


def events(client, id):
    return client.get(f'/levels/{id}/events').json()


@pytest.mark.parametrize('offset,expected', [(49, 'DISARMED'), (-49, 'DISARMED'),
    (50, 'ACTIVE'), (-50, 'ACTIVE'), (51, 'ACTIVE'), (-51, 'ACTIVE')])
def test_entry_and_rearm_boundary(client, offset, expected):
    id = level(client)
    ticks(client, 24900, 25000)
    assert state(client, id) == 'DISARMED'
    trade, = client.get('/trades').json()
    assert events(client, id)[0]['trade_id'] == trade['trade_id']
    ticks(client, 25000 + offset, 25000 + offset)
    assert state(client, id) == expected
    assert [e['event_type'] for e in events(client, id)] == (
        ['LEVEL_DISARMED', 'LEVEL_REARMED'] if expected == 'ACTIVE' else ['LEVEL_DISARMED'])
    assert len(client.get('/signals').json()) == 1


def test_disarmed_suppresses_signals_and_trades(client):
    id = level(client)
    ticks(client, 24900, 25000, 25001, 24999, 25000, 25000)
    assert state(client, id) == 'DISARMED'
    assert len(client.get('/signals').json()) == len(client.get('/trades').json()) == 1
    assert len(events(client, id)) == 1


def test_rejected_and_failed_entry_do_not_disarm(tmp_path):
    with TestClient(create_app(tmp_path / 'test.db', option_prices=SimulatedOptionPrices())) as client:
        id = level(client)
        ticks(client, 25000)  # Insufficient history.
        assert not client.get('/signals').json()[0]['valid']
        assert state(client, id) == 'ACTIVE'
        ticks(client, 24900, 25000)  # Valid signal, missing option quote.
        assert client.get('/signals').json()[0]['valid']
        assert client.get('/trade-entry-results').json()[0]['failure_reason'] == 'OPTION_PRICE_UNAVAILABLE'
        assert state(client, id) == 'ACTIVE'
        assert events(client, id) == []


def test_distance_rejection_does_not_disarm(tmp_path):
    with TestClient(create_app(tmp_path / 'test.db', signal_settings=SignalSettings(
            minimum_approach_distance_enabled=True, minimum_approach_distance_points=100))) as client:
        id = level(client)
        ticks(client, 24999, 25000)
        assert state(client, id) == 'ACTIVE'
        assert client.get('/signals').json()[0]['rejection_reason'] == 'MINIMUM_DISTANCE_NOT_MET'


def test_independent_levels_and_later_return(client):
    first, second = level(client), level(client, 25030)
    ticks(client, 24900, 25000)
    assert state(client, first) == 'DISARMED'
    assert state(client, second) == 'ACTIVE'
    # Close the original position through existing stop logic.
    trade = client.get('/trades').json()[0]
    ticks(client, 90, instrument=trade['option_symbol'])
    ticks(client, 24950)  # Re-arm below without touching the other level.
    assert state(client, first) == 'ACTIVE'
    ticks(client, 25000)
    assert len(client.get('/trades').json()) == 2
    assert state(client, first) == 'DISARMED'
    assert state(client, second) == 'ACTIVE'
    assert [e['event_type'] for e in events(client, first)] == [
        'LEVEL_DISARMED', 'LEVEL_REARMED', 'LEVEL_DISARMED']


def test_restart_preserves_disarmed_and_edit_resets_initial_arm(tmp_path):
    path = tmp_path / 'test.db'
    with TestClient(create_app(path)) as client:
        id = level(client)
        ticks(client, 24900, 25000)
        original_events = events(client, id)
    with TestClient(create_app(path)) as client:
        assert state(client, id) == 'DISARMED'
        assert events(client, id) == original_events
        for enabled in (False, True):
            client.put(f'/levels/{id}', json=dict(instrument='NIFTY', price=25000, enabled=enabled))
            assert state(client, id) == 'PENDING_ARM'
        ticks(client, 25000, 25029)
        assert state(client, id) == 'PENDING_ARM'
        assert len(client.get('/signals').json()) == 1
        ticks(client, 25030)
        assert state(client, id) == 'ACTIVE'


def test_setting_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('LEVEL_REARM_DISTANCE_POINTS', '75')
    with TestClient(create_app(tmp_path / 'test.db')) as client:
        id = level(client)
        ticks(client, 24900, 25000, 25050)
        assert state(client, id) == 'DISARMED'
        ticks(client, 25075)
        assert state(client, id) == 'ACTIVE'


def test_legacy_migration(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE levels (id INTEGER PRIMARY KEY, instrument TEXT, price REAL, enabled INTEGER, created_at TEXT, updated_at TEXT)')
        c.execute("INSERT INTO levels VALUES (1, 'NIFTY', 25000, 1, '2026-09-14', '2026-09-14')")
    initialize_database(path)
    with connect(path) as c:
        assert c.execute('SELECT status FROM levels').fetchone()[0] == 'ACTIVE'
        c.execute("UPDATE levels SET status = 'DISARMED'")
    initialize_database(path)
    with connect(path) as c:
        assert c.execute('SELECT status FROM levels').fetchone()[0] == 'DISARMED'


def test_entry_and_disarm_roll_back_together(tmp_path, monkeypatch):
    from app.level_repository import LevelRepository
    path = tmp_path / 'test.db'
    with TestClient(create_app(path)) as client:
        id = level(client)
        ticks(client, 24900)
        original = LevelRepository.change_status
        def fail_after_change(self, *args, **kwargs):
            original(self, *args, **kwargs)
            raise RuntimeError('simulated write failure')
        with monkeypatch.context() as patch:
            patch.setattr(LevelRepository, 'change_status', fail_after_change)
            with pytest.raises(RuntimeError, match='simulated write failure'):
                ticks(client, 25000)
        assert state(client, id) == 'ACTIVE'
        assert client.get('/trades').json() == []
        assert events(client, id) == []
        ticks(client, 25000)
        assert state(client, id) == 'DISARMED'


def test_replayed_entry_does_not_disarm_again_after_rearm(client):
    from app.signal_models import SignalResult
    from app.option_models import StoredOptionSelection
    id = level(client)
    ticks(client, 24900, 25000)
    signal = SignalResult(**client.get('/signals').json()[0])
    selection = StoredOptionSelection(**client.get('/option-selections').json()[0])
    ticks(client, 24950)
    client.app.state.paper_executor.execute(signal, selection, signal.timestamp)
    assert state(client, id) == 'ACTIVE'
    assert len(events(client, id)) == 2
    assert len(client.get('/trades').json()) == 1


def test_option_prices_do_not_rearm(client):
    id = level(client)
    ticks(client, 24900, 25000)
    trade = client.get('/trades').json()[0]
    ticks(client, 150, instrument=trade['option_symbol'])
    assert state(client, id) == 'DISARMED'


@pytest.mark.parametrize('value', [0, -1, float('inf'), float('nan')])
def test_rearm_distance_requires_positive_finite_value(value):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TradeSettings(level_rearm_distance_points=value)
