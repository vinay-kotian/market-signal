from active_level_fixture import create_active_level, create_active_record
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.database import connect, initialize_database
from app.main import create_app
from app.settings import TradeSettings
from app.signal_models import SignalResult
from app.option_models import StoredOptionSelection
from app.trade_events import TradeEventRepository
from app.trade_repository import TradeRepository


def tick(client, symbol, price):
    response = client.post('/simulation/tick', json={'instrument': symbol, 'price': price})
    assert response.status_code == 200


def enter(client):
    assert create_active_level(client, json={'instrument': 'NIFTY', 'price': 25000, 'enabled': True}).status_code == 201
    tick(client, 'NIFTY', 24900)
    tick(client, 'NIFTY', 25000)
    return client.get('/trades').json()[0]


@pytest.mark.parametrize('percentage,stop', [(10, 90), (15, 85), (12.5, 87.5)])
def test_initial_stop_calculation(tmp_path, percentage, stop):
    with TestClient(create_app(tmp_path / 'stops.sqlite3', trade_settings=TradeSettings(stop_loss_percentage=percentage))) as client:
        trade = enter(client)
        assert trade['initial_stop_loss'] == stop
        assert trade['stop_loss_percentage'] == percentage
        assert trade['exit_price'] is None
        assert trade['realised_pnl'] is None
        events = client.get(f"/trades/{trade['trade_id']}/events").json()
        assert [e['event_type'] for e in events] == ['POSITION_OPENED']
        assert events[0]['reconstructed'] is False


@pytest.mark.parametrize('price,status,pnl,pct', [
    (90.01, 'OPEN', None, None), (90, 'CLOSED', -100, -10),
    (85, 'CLOSED', -150, -15), (0, 'CLOSED', -1000, -100),
])
def test_stops_and_pnl(client, price, status, pnl, pct):
    trade = enter(client)
    tick(client, trade['option_symbol'], price)
    result = client.get('/trades').json()[0]
    assert result['status'] == status
    assert result['realised_pnl'] == pnl
    assert result['realised_pnl_percentage'] == pct
    if status == 'CLOSED':
        assert result['exit_price'] == price
        assert result['exit_reason'] == 'STOP_LOSS'
        assert result['exit_time'] is not None
    assert len(client.get('/signals').json()) == 1  # Option tick is not an underlying tick.


def test_closed_trade_and_duplicate_ticks_are_ignored(client):
    trade = enter(client)
    tick(client, trade['option_symbol'], 90)
    closed = client.get('/trades').json()
    events = client.get(f"/trades/{trade['trade_id']}/events").json()
    assert [e['event_type'] for e in events] == ['POSITION_OPENED', 'STOP_LOSS_HIT', 'POSITION_CLOSED']
    for price in [90, 90, 50, 120]:
        tick(client, trade['option_symbol'], price)
    assert client.get('/trades').json() == closed
    assert client.get(f"/trades/{trade['trade_id']}/events").json() == events


def test_reload_preserves_stop_exit_and_events(tmp_path):
    path = tmp_path / 'restart.sqlite3'
    with TestClient(create_app(path)) as client:
        trade = enter(client)
        signal = SignalResult(**client.get('/signals').json()[0])
        selection = StoredOptionSelection(**client.get('/option-selections').json()[0])
    # New settings must never replace an existing position's persisted stop.
    app = create_app(path, trade_settings=TradeSettings(stop_loss_percentage=50))
    with TestClient(app) as client:
        assert client.get('/trades').json()[0]['initial_stop_loss'] == 90
        tick(client, trade['option_symbol'], 89)
        closed = client.get('/trades').json()[0]
        outcome = app.state.paper_executor.execute(signal, selection, datetime.now(timezone.utc))
        assert outcome.status == 'CLOSED'
        assert client.get('/trades').json() == [closed]
    assert TradeRepository(path).recent()[0].status == 'CLOSED'
    assert len(TradeEventRepository(path).for_trade(trade['trade_id'])) == 3
    with TestClient(create_app(path)) as client:
        tick(client, trade['option_symbol'], 80)
        assert client.get('/trades').json() == [closed]


def test_multiple_positions_only_matching_symbol_closes(client):
    first = enter(client)
    tick(client, 'NIFTY', 25100)
    tick(client, 'NIFTY', 24900)  # Opposite direction creates CE instead of PE.
    second = client.get('/trades').json()[0]
    assert first['option_symbol'] != second['option_symbol']
    tick(client, first['option_symbol'], 90)
    trades = {t['trade_id']: t for t in client.get('/trades').json()}
    assert trades[first['trade_id']]['status'] == 'CLOSED'
    assert trades[second['trade_id']]['status'] == 'OPEN'


def test_all_open_positions_are_monitored_beyond_recent_limit(tmp_path):
    path = tmp_path / 'many.sqlite3'
    with TestClient(create_app(path)) as client:
        trade = enter(client)
        with connect(path) as connection:
            for index in range(2, 103):
                connection.execute("""INSERT INTO trades (
                    signal_id, option_selection_id, instrument, trigger_level, direction,
                    option_symbol, option_type, strike, expiry, lot_size, number_of_lots,
                    quantity, entry_price, entry_time, trade_mode, status,
                    stop_loss_percentage, initial_stop_loss)
                    SELECT ?, ?, instrument, trigger_level, direction, option_symbol,
                    option_type, strike, expiry, lot_size, number_of_lots, quantity,
                    entry_price, entry_time, trade_mode, status, stop_loss_percentage,
                    initial_stop_loss FROM trades WHERE trade_id = ?""", (index, index, trade['trade_id']))
        tick(client, trade['option_symbol'], 90)
        with connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM trades WHERE status = 'CLOSED'").fetchone()[0] == 102


def test_failed_event_write_rolls_back_close(tmp_path):
    path = tmp_path / 'rollback.sqlite3'
    with TestClient(create_app(path), raise_server_exceptions=False) as client:
        trade = enter(client)
        with connect(path) as connection:
            connection.execute("""CREATE TRIGGER fail_event BEFORE INSERT ON trade_events
                WHEN NEW.event_type = 'POSITION_CLOSED'
                BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        assert client.post('/simulation/tick', json={'instrument': trade['option_symbol'], 'price': 85}).status_code == 500
        assert client.get('/trades').json()[0]['status'] == 'OPEN'
        assert len(client.get(f"/trades/{trade['trade_id']}/events").json()) == 1
        with connect(path) as connection:
            connection.execute('DROP TRIGGER fail_event')
        tick(client, trade['option_symbol'], 85)
        assert client.get('/trades').json()[0]['status'] == 'CLOSED'


def test_option_tick_updates_quote_and_negative_price_is_rejected(client):
    trade = enter(client)
    assert client.post('/simulation/tick', json={'instrument': trade['option_symbol'], 'price': -1}).status_code == 422
    assert client.get('/trades').json()[0]['status'] == 'OPEN'
    tick(client, trade['option_symbol'], 110)
    tick(client, 'NIFTY', 24950)  # Re-arm before testing the next entry quote.
    tick(client, 'NIFTY', 25000)
    assert client.get('/trades').json()[0]['entry_price'] == 110
    assert client.get('/trades').json()[0]['initial_stop_loss'] == 99


def test_stop_setting_validation(monkeypatch):
    monkeypatch.setenv('STOP_LOSS_PERCENTAGE', '12.5')
    assert TradeSettings.from_environment().stop_loss_percentage == 12.5
    for value in [0, -1, 100, float('inf')]:
        with pytest.raises(ValidationError):
            TradeSettings(stop_loss_percentage=value)


def test_legacy_migration_preserves_entries_and_allows_close(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with TestClient(create_app(path)) as client:
        original = enter(client)
    # Recreate the exact previous milestone's table, including its OPEN-only constraint.
    with connect(path) as connection:
        connection.execute('ALTER TABLE trades RENAME TO new_trades')
        connection.execute(LEGACY_SCHEMA)
        columns = [row['name'] for row in connection.execute('PRAGMA table_info(trades)')]
        names = ', '.join(columns)
        connection.execute(f'INSERT INTO trades ({names}) SELECT {names} FROM new_trades')
        connection.execute('DROP TABLE new_trades')
        connection.execute('DROP TABLE trade_events')
    with TestClient(create_app(path, trade_settings=TradeSettings(stop_loss_percentage=20, trailing_stop_percentage=20))) as client:
        migrated = client.get('/trades').json()[0]
        assert migrated['initial_stop_loss'] == 80
        assert {key: migrated[key] for key in columns} == {key: original[key] for key in columns}
        events = client.get(f"/trades/{original['trade_id']}/events").json()
        assert len(events) == 1 and events[0]['reconstructed'] is True
        tick(client, original['option_symbol'], 80)
        assert client.get('/trades').json()[0]['status'] == 'CLOSED'
    initialize_database(path, 50)
    assert TradeRepository(path).recent()[0].initial_stop_loss == 80
    assert len(TradeEventRepository(path).for_trade(original['trade_id'])) == 3


LEGACY_SCHEMA = """CREATE TABLE trades (
                trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                option_selection_id INTEGER NOT NULL UNIQUE,
                instrument TEXT NOT NULL, trigger_level REAL NOT NULL,
                direction TEXT NOT NULL, option_symbol TEXT NOT NULL,
                option_type TEXT NOT NULL, strike INTEGER NOT NULL, expiry TEXT NOT NULL,
                lot_size INTEGER NOT NULL CHECK(lot_size > 0),
                number_of_lots INTEGER NOT NULL CHECK(number_of_lots > 0),
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                entry_price REAL NOT NULL CHECK(entry_price > 0), entry_time TEXT NOT NULL,
                trade_mode TEXT NOT NULL CHECK(trade_mode = 'PAPER'),
                status TEXT NOT NULL CHECK(status = 'OPEN')
            )"""
