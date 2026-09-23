from active_level_fixture import create_active_level, create_active_record
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.database import connect, initialize_database
from app.main import create_app
from app.settings import TradeSettings
from app.trade_repository import TradeRepository


def enter(client):
    create_active_level(client, json={'instrument': 'NIFTY', 'price': 25000, 'enabled': True})
    for price in [24900, 25000]:
        assert client.post('/simulation/tick', json={'instrument': 'NIFTY', 'price': price}).status_code == 200
    return client.get('/trades').json()[0]


def send(client, trade, price):
    assert client.post('/simulation/tick', json={'instrument': trade['option_symbol'], 'price': price}).status_code == 200
    return client.get('/trades').json()[0]


def events(client, trade):
    return client.get(f"/trades/{trade['trade_id']}/events").json()


def test_complete_example_and_duplicate_ticks(client):
    trade = enter(client)
    assert trade['highest_price'] == 100 and trade['current_stop_loss'] == 90
    for price, high, stop, active in [(105, 105, 94.5, False), (110, 110, 100, True),
                                      (120, 120, 108, True), (115, 120, 108, True)]:
        result = send(client, trade, price)
        assert (result['highest_price'], result['current_stop_loss'], result['breakeven_activated']) == (high, stop, active)
        before = events(client, trade)
        assert send(client, trade, price) == result
        assert events(client, trade) == before
    closed = send(client, trade, 108)
    assert closed['status'] == 'CLOSED'
    assert closed['realised_pnl'] == 80
    assert closed['realised_pnl_percentage'] == 8
    assert [event['event_type'] for event in events(client, trade)] == [
        'POSITION_OPENED', 'TRAILING_STOP_UPDATED', 'BREAKEVEN_PROTECTION_ACTIVATED',
        'TRAILING_STOP_UPDATED', 'STOP_LOSS_HIT', 'POSITION_CLOSED',
    ]
    before = events(client, trade)
    for price in [108, 80, 200]:
        assert send(client, trade, price) == closed
    assert events(client, trade) == before


def test_initial_stop_wins_until_trailing_exceeds_it(tmp_path):
    with TestClient(create_app(tmp_path / 'initial.sqlite3', trade_settings=TradeSettings(
        trailing_stop_percentage=20, breakeven_protection_enabled=False))) as client:
        trade = enter(client)
        for price in [105, 110, 112.5]:
            assert send(client, trade, price)['current_stop_loss'] == 90
        assert len(events(client, trade)) == 1
        assert send(client, trade, 115)['current_stop_loss'] == 92
        assert send(client, trade, 100)['current_stop_loss'] == 92
        assert len(events(client, trade)) == 2


@pytest.mark.parametrize('lock,stop', [(0, 100), (1, 101)])
def test_activation_threshold_and_lock(tmp_path, lock, stop):
    with TestClient(create_app(tmp_path / 'lock.sqlite3', trade_settings=TradeSettings(
        breakeven_lock_percent=lock))) as client:
        trade = enter(client)
        assert send(client, trade, 109.99)['breakeven_activated'] is False
        assert not any(e['event_type'] == 'BREAKEVEN_PROTECTION_ACTIVATED' for e in events(client, trade))
        result = send(client, trade, 110)
        assert result['current_stop_loss'] == stop and result['breakeven_activated']
        assert send(client, trade, stop)['status'] == 'CLOSED'


def test_breakeven_disabled(tmp_path):
    with TestClient(create_app(tmp_path / 'disabled.sqlite3', trade_settings=TradeSettings(
        breakeven_protection_enabled=False))) as client:
        trade = enter(client)
        result = send(client, trade, 110)
        assert result['current_stop_loss'] == 99
        assert result['breakeven_activated'] is False
        assert [e['event_type'] for e in events(client, trade)] == ['POSITION_OPENED', 'TRAILING_STOP_UPDATED']


def test_activation_once_even_when_trailing_already_stronger(client):
    trade = enter(client)
    result = send(client, trade, 120)
    assert result['current_stop_loss'] == 108
    for price in [120, 125, 121, 130]:
        send(client, trade, price)
    history = events(client, trade)
    assert sum(e['event_type'] == 'BREAKEVEN_PROTECTION_ACTIVATED' for e in history) == 1
    updates = [e for e in history if e['event_type'] == 'TRAILING_STOP_UPDATED']
    assert len(updates) == 3
    assert all(e['current_stop'] > e['previous_stop'] for e in updates)


def test_restart_keeps_high_stop_activation_and_settings(tmp_path):
    path = tmp_path / 'restart.sqlite3'
    with TestClient(create_app(path)) as client:
        trade = enter(client)
        result = send(client, trade, 120)
        history = events(client, trade)
    with TestClient(create_app(path, trade_settings=TradeSettings(
        trailing_stop_percentage=50, breakeven_protection_enabled=False))) as client:
        assert send(client, trade, 115) == result
        assert events(client, trade) == history
        closed = send(client, trade, 108)
        assert closed['status'] == 'CLOSED'
        assert closed['exit_reason'] == 'TRAILING_STOP_LOSS'
    assert TradeRepository(path).recent()[0].highest_price == 120


def test_protection_and_events_rollback_together(tmp_path):
    path = tmp_path / 'rollback.sqlite3'
    with TestClient(create_app(path), raise_server_exceptions=False) as client:
        trade = enter(client)
        with connect(path) as connection:
            connection.execute("""CREATE TRIGGER fail_activation BEFORE INSERT ON trade_events
                WHEN NEW.event_type = 'BREAKEVEN_PROTECTION_ACTIVATED'
                BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        assert client.post('/simulation/tick', json={'instrument': trade['option_symbol'], 'price': 110}).status_code == 500
        assert client.get('/trades').json()[0] == trade
        assert len(events(client, trade)) == 1
        with connect(path) as connection:
            connection.execute('DROP TRIGGER fail_activation')
        assert send(client, trade, 110)['current_stop_loss'] == 100


def test_initial_only_schema_migration_preserves_events(tmp_path):
    path = tmp_path / 'migration.sqlite3'
    with TestClient(create_app(path)) as client:
        trade = enter(client)
        original_events = events(client, trade)
    with connect(path) as connection:
        for name in ['highest_price', 'current_stop_loss', 'breakeven_activated', 'trailing_stop_percentage',
                     'breakeven_protection_enabled', 'breakeven_activation_percent', 'breakeven_lock_percent']:
            connection.execute(f'ALTER TABLE trades DROP COLUMN {name}')
        connection.execute('DROP INDEX once_per_trade_event')
        connection.execute('DROP INDEX distinct_trailing_stop')
        connection.execute('ALTER TABLE trade_events RENAME TO events_new')
        connection.execute("""CREATE TABLE trade_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('POSITION_OPENED','STOP_LOSS_HIT','POSITION_CLOSED')),
            price REAL NOT NULL, timestamp TEXT NOT NULL, reconstructed INTEGER NOT NULL DEFAULT 0,
            UNIQUE(trade_id, event_type))""")
        connection.execute('INSERT INTO trade_events SELECT id, trade_id, event_type, price, timestamp, reconstructed FROM events_new')
        connection.execute('DROP TABLE events_new')
    with TestClient(create_app(path)) as client:
        assert client.get('/trades').json()[0] == trade
        assert events(client, trade) == original_events
        send(client, trade, 105)
        send(client, trade, 106)
        assert len(events(client, trade)) == 3  # More than one trailing event is supported.
    initialize_database(path)
    assert TradeRepository(path).recent()[0].current_stop_loss == 95.4


def test_settings_defaults_and_environment(monkeypatch):
    default = TradeSettings()
    assert (default.trailing_stop_percentage, default.breakeven_protection_enabled,
            default.breakeven_activation_percent, default.breakeven_lock_percent) == (10, True, 10, 0)
    monkeypatch.setenv('TRAILING_STOP_PERCENTAGE', '15')
    monkeypatch.setenv('BREAKEVEN_PROTECTION_ENABLED', 'false')
    monkeypatch.setenv('BREAKEVEN_ACTIVATION_PERCENT', '12')
    monkeypatch.setenv('BREAKEVEN_LOCK_PERCENT', '1')
    settings = TradeSettings.from_environment()
    assert (settings.trailing_stop_percentage, settings.breakeven_protection_enabled,
            settings.breakeven_activation_percent, settings.breakeven_lock_percent) == (15, False, 12, 1)
    for values in [dict(trailing_stop_percentage=0), dict(trailing_stop_percentage=100),
                   dict(breakeven_activation_percent=-1), dict(breakeven_lock_percent=-1)]:
        with pytest.raises(ValidationError):
            TradeSettings(**values)
