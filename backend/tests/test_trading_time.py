import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.settings import TradeSettings
from test_paper_trades import add_level, publish


class Clock:
    def __init__(self, value='2026-09-14T10:00:00'):
        self.set(value)

    def set(self, value):
        self.value = datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Asia/Kolkata'))

    def __call__(self):
        return self.value


def enter(client):
    add_level(client)
    publish(client, [24900, 25000])
    return client.get('/trades').json()


@pytest.mark.parametrize('hour,reason', [
    ('09:14:59', 'BEFORE_TRADING_START'),
    ('09:15:00', None), ('12:00:00', None), ('15:15:00', None),
    ('15:15:01', 'NEW_TRADE_CUTOFF_REACHED'),
    ('15:25:00', 'NEW_TRADE_CUTOFF_REACHED'),
])
def test_entry_window(tmp_path, hour, reason):
    with TestClient(create_app(tmp_path / 'db', clock=Clock('2026-09-14T' + hour))) as client:
        trades = enter(client)
        result, = client.get('/trade-entry-results').json()
        assert result['failure_reason'] == reason
        assert len(trades) == (0 if reason else 1)


def test_positions_still_monitored_after_cutoff(tmp_path):
    clock = Clock()
    with TestClient(create_app(tmp_path / 'db', clock=clock)) as client:
        trade, = enter(client)
        clock.set('2026-09-14T15:16:00')
        publish(client, [105], trade['option_symbol'])
        assert client.get('/trades').json()[0]['status'] == 'OPEN'
        publish(client, [90], trade['option_symbol'])
        closed = client.get('/trades').json()[0]
        assert closed['current_stop_loss'] == 94.5
        assert closed['exit_reason'] == 'TRAILING_STOP_LOSS'


def test_market_exit_without_tick_pnl_and_duplicates(tmp_path):
    clock = Clock()
    app = create_app(tmp_path / 'db', clock=clock)
    with TestClient(app) as client:
        trade, = enter(client)
        publish(client, [105], trade['option_symbol'])
        clock.set('2026-09-14T15:24:59')
        asyncio.run(app.state.market_close.check())
        assert client.get('/trades').json()[0]['status'] == 'OPEN'
        clock.set('2026-09-14T15:25:00')
        asyncio.run(app.state.market_close.check())
        closed, = client.get('/trades').json()
        assert closed['status'] == 'CLOSED'
        assert closed['exit_reason'] == 'MARKET_CLOSING_EXIT'
        assert closed['exit_price'] == 105
        assert datetime.fromisoformat(closed['exit_time']) == clock()
        assert closed['realised_pnl'] == 5 * trade['quantity']
        assert closed['realised_pnl_percentage'] == 5
        events = app.state.trade_events.for_trade(trade['trade_id'])
        kinds = [event.event_type for event in events]
        assert kinds.count('MARKET_CLOSING_EXIT_TRIGGERED') == 1
        assert kinds.count('POSITION_CLOSED') == 1
        asyncio.run(app.state.market_close.check())
        publish(client, [85, 85], trade['option_symbol'])
        assert client.get('/trades').json() == [closed]
        assert app.state.trade_events.for_trade(trade['trade_id']) == events


def test_restart_closes_overdue_position_using_persisted_quote(tmp_path):
    clock = Clock()
    path = tmp_path / 'db'
    with TestClient(create_app(path, clock=clock)) as client:
        trade, = enter(client)
        publish(client, [105], trade['option_symbol'])
    clock.set('2026-09-15T09:00:00')
    app = create_app(path, clock=clock)
    with TestClient(app) as client:
        closed, = client.get('/trades').json()
        assert closed['exit_reason'] == 'MARKET_CLOSING_EXIT'
        assert closed['exit_price'] == 105
        events = app.state.trade_events.for_trade(trade['trade_id'])
    with TestClient(create_app(path, clock=clock)) as client:
        assert client.get('/trades').json() == [closed]
        assert app.state.trade_events.for_trade(trade['trade_id']) == events


def test_event_loop_exits_without_requests(tmp_path):
    clock = Clock()
    app = create_app(tmp_path / 'db', clock=clock)
    with TestClient(app) as client:
        enter(client)
        clock.set('2026-09-14T15:25:00')
        # Let the lifespan task run without any simulated tick or API request.
        async def wait_for_close():
            for _ in range(60):
                if app.state.trade_repository.recent()[0].status == 'CLOSED':
                    return
                await asyncio.sleep(0.05)
            pytest.fail('Background mandatory exit did not run')
        asyncio.run(wait_for_close())
        assert client.get('/trades').json()[0]['exit_reason'] == 'MARKET_CLOSING_EXIT'


def test_deadline_tick_uses_incoming_quote(tmp_path):
    clock = Clock()
    with TestClient(create_app(tmp_path / 'db', clock=clock)) as client:
        trade, = enter(client)
        clock.set('2026-09-14T15:25:00')
        publish(client, [85], trade['option_symbol'])
        closed, = client.get('/trades').json()
        assert closed['exit_reason'] == 'MARKET_CLOSING_EXIT'
        assert closed['exit_price'] == 85
        assert closed['realised_pnl_percentage'] == -15


def test_custom_time_settings(monkeypatch):
    monkeypatch.setenv('TRADING_START_TIME', '10:00')
    assert TradeSettings.from_environment().trading_start_time.hour == 10
    with pytest.raises(ValidationError):
        TradeSettings(new_trade_cutoff_time='16:00')
    with pytest.raises(ValidationError):
        TradeSettings(trading_start_time='09:15+05:30')


def test_failed_event_write_rolls_back_close(tmp_path):
    from app.database import connect
    clock = Clock()
    path = tmp_path / 'db'
    app = create_app(path, clock=clock)
    with TestClient(app) as client:
        trade, = enter(client)
        with connect(path) as connection:
            connection.execute("""CREATE TRIGGER reject_exit BEFORE INSERT ON trade_events
                WHEN NEW.event_type = 'POSITION_CLOSED'
                BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        clock.set('2026-09-14T15:25:00')
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            asyncio.run(app.state.market_close.check())
        assert client.get('/trades').json()[0]['status'] == 'OPEN'
        assert [e.event_type for e in app.state.trade_events.for_trade(trade['trade_id'])] == ['POSITION_OPENED']
        with connect(path) as connection:
            connection.execute('DROP TRIGGER reject_exit')
        asyncio.run(app.state.market_close.check())
        assert client.get('/trades').json()[0]['status'] == 'CLOSED'
