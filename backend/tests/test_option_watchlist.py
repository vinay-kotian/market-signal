"""Watchlist membership follows committed trades, independently of trading decisions."""
import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.main import create_app
from app.option_models import StoredOptionSelection
from app.signal_models import SignalResult
from app.trade_models import TradeEntry
from app.trade_repository import TradeRepository
from test_position_monitor import enter, tick
from test_backtests import run, dataset
from test_live_feed import until_price
from test_zerodha import live, frame
from active_level_fixture import create_active_level


def options(client):
    response = client.get('/watchlist/options')
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize('prices,option_type', [([24900, 25000], 'PE'), ([25100, 25000], 'CE')])
@pytest.mark.parametrize('instrument,level', [('NIFTY', 25000), ('BANKNIFTY', 51000)])
def test_successful_entry_adds_selected_contract(client, prices, option_type, instrument, level):
    create_active_level(client, json=dict(instrument=instrument, price=level, enabled=True))
    for price in prices:
        tick(client, instrument, price - 25000 + level)
    trade, = client.get('/trades').json()
    item, = options(client)
    for field in ('trade_id', 'option_symbol', 'strike', 'expiry', 'instrument', 'entry_price'):
        assert item[field] == trade[field]
    assert item['option_type'] == option_type
    assert item['entry_price'] == item['current_ltp'] == trade['entry_price']
    assert item['status'] == 'ACTIVE'
    assert item['change_from_entry_percentage'] == item['unrealized_pnl_percentage'] == 0
    assert item['watchlist_date'] == '2026-09-14'


def test_failed_entry_does_not_add_contract(client):
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    client.app.state.option_prices._prices.clear()
    tick(client, 'NIFTY', 24900)
    tick(client, 'NIFTY', 25000)
    assert client.get('/trade-entry-results').json()[0]['failure_reason'] == 'OPTION_PRICE_UNAVAILABLE'
    assert options(client) == []


def test_duplicate_entry_and_reentry_use_one_contract_row(client):
    trade = enter(client)
    signal = SignalResult(**client.get('/signals').json()[0])
    selection = StoredOptionSelection(**client.get('/option-selections').json()[0])
    executor = client.app.state.paper_executor
    for _ in range(2):
        executor.execute(signal, selection, signal.timestamp)
    assert len(options(client)) == 1
    tick(client, trade['option_symbol'], 90)
    assert client.delete('/watchlist/options/' + trade['option_symbol']).status_code == 204
    executor.execute(signal, selection, signal.timestamp)
    assert options(client) == []  # A duplicate closed selection cannot undo removal.
    tick(client, trade['option_symbol'], 110)
    tick(client, 'NIFTY', 24900)
    tick(client, 'NIFTY', 25000)
    item, = options(client)
    assert item['option_symbol'] == trade['option_symbol']
    assert item['trade_id'] != trade['trade_id']
    assert item['entry_price'] == 110 and item['status'] == 'ACTIVE'
    with connect(client.app.state.database_path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM option_watchlist').fetchone()[0] == 1


def test_quote_updates_close_and_closed_contract_continues_updating(client):
    trade = enter(client)
    with client.websocket_connect('/ws/market') as socket:
        tick(client, trade['option_symbol'], 120)
        update, = [e['data'] for e in until_price(socket) if e['type'] == 'OPTION_WATCHLIST_UPDATED']
        assert update == options(client)[0]
        assert update['current_ltp'] == 120 and update['unrealized_pnl_percentage'] == 20
        tick(client, trade['option_symbol'], 108)
        item, = [e['data'] for e in until_price(socket) if e['type'] == 'OPTION_WATCHLIST_UPDATED']
        assert item['status'] == 'CLOSED' and item['unrealized_pnl_percentage'] is None
        assert item['realised_pnl_percentage'] == 8
        tick(client, trade['option_symbol'], 130)
        item, = [e['data'] for e in until_price(socket) if e['type'] == 'OPTION_WATCHLIST_UPDATED']
        assert item['current_ltp'] == 130 and item['change_from_entry_percentage'] == 30
        assert item['realised_pnl_percentage'] == 8  # LTP changes do not change a closed trade.
        assert client.get('/trades').json()[0]['exit_price'] == 108


def test_manual_removal_only_for_closed_and_broadcasts(client):
    trade = enter(client)
    path = '/watchlist/options/' + trade['option_symbol']
    assert client.delete(path).status_code == 409
    tick(client, trade['option_symbol'], 90)
    with client.websocket_connect('/ws/market') as socket:
        assert client.delete(path).status_code == 204
        event = socket.receive_json()
        assert event['type'] == 'OPTION_WATCHLIST_REMOVED'
        assert event['data']['option_symbol'] == trade['option_symbol']
    assert options(client) == []
    assert client.delete(path).status_code == 404
    assert client.get('/trades').json()[0]['status'] == 'CLOSED'


def test_membership_quotes_and_removal_survive_refresh_restart(tmp_path):
    path = tmp_path / 'db.sqlite3'
    with TestClient(create_app(path)) as client:
        trade = enter(client)
        tick(client, trade['option_symbol'], 105)
        before = options(client)
        assert options(client) == before
    with TestClient(create_app(path)) as client:
        assert options(client) == before
        tick(client, trade['option_symbol'], 90)
        closed = options(client)
    with TestClient(create_app(path)) as client:
        assert options(client) == closed
        assert client.delete('/watchlist/options/' + trade['option_symbol']).status_code == 204
    with TestClient(create_app(path)) as client:
        assert options(client) == []
        with connect(path) as connection:
            assert connection.execute('SELECT removed_at FROM option_watchlist').fetchone()[0] is not None


def test_closed_expires_at_kolkata_midnight_active_remains(tmp_path):
    now = [datetime.fromisoformat('2026-09-14T10:00:00+05:30')]
    with TestClient(create_app(tmp_path / 'db', clock=lambda: now[0])) as client:
        enter(client)
        now[0] = datetime.fromisoformat('2026-09-14T23:59:59+05:30')
        client.portal.call(client.app.state.market_close.check)
        assert options(client)[0]['status'] == 'CLOSED'
        now[0] = datetime.fromisoformat('2026-09-15T00:00:00+05:30')
        assert options(client) == []
    now[0] = datetime.fromisoformat('2026-09-15T10:00:00+05:30')
    with TestClient(create_app(tmp_path / 'overnight', clock=lambda: now[0])) as client:
        enter(client)
        now[0] = datetime.fromisoformat('2026-09-16T00:00:00+05:30')
        assert options(client)[0]['status'] == 'ACTIVE'
        client.portal.call(client.app.state.market_close.check)
        assert options(client)[0]['watchlist_date'] == '2026-09-16'
        assert options(client)[0]['status'] == 'CLOSED'


def test_backtest_isolation_including_mixed_mode_database(client):
    trade = enter(client)
    before = options(client)
    run(client, dataset([('10:02:00', 90)]))
    assert options(client) == before
    entry = TradeEntry(**{**trade, 'trade_mode': 'BACKTEST', 'signal_id': 900,
                          'option_selection_id': 900, 'option_symbol': 'BACKTEST-ONLY'})
    TradeRepository(client.app.state.database_path, mode='BACKTEST').save(entry)
    assert options(client) == before
    with connect(client.app.state.database_path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM option_watchlist').fetchone()[0] == 1
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert options(restarted) == before


def test_entry_and_close_membership_roll_back_with_trade(client):
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    tick(client, 'NIFTY', 24900)
    with connect(client.app.state.database_path) as connection:
        connection.execute("""CREATE TRIGGER fail_entry BEFORE INSERT ON trade_events
            WHEN NEW.event_type = 'POSITION_OPENED' BEGIN SELECT RAISE(ABORT, 'entry rollback'); END""")
    with pytest.raises(Exception, match='entry rollback'):
        tick(client, 'NIFTY', 25000)
    assert options(client) == [] and client.get('/trades').json() == []
    with connect(client.app.state.database_path) as connection:
        connection.execute('DROP TRIGGER fail_entry')
    tick(client, 'NIFTY', 25000)
    trade, = client.get('/trades').json()
    with connect(client.app.state.database_path) as connection:
        connection.execute("""CREATE TRIGGER fail_close BEFORE INSERT ON trade_events
            WHEN NEW.event_type = 'POSITION_CLOSED' BEGIN SELECT RAISE(ABORT, 'close rollback'); END""")
    with pytest.raises(Exception, match='close rollback'):
        tick(client, trade['option_symbol'], 90)
    assert options(client)[0]['status'] == 'ACTIVE'
    assert client.get('/trades').json()[0]['status'] == 'OPEN'


def test_existing_trades_are_backfilled(tmp_path):
    path = tmp_path / 'migration'
    with TestClient(create_app(path)) as client:
        trade = enter(client)
        with connect(path) as connection:
            connection.execute('DELETE FROM option_watchlist')
    with TestClient(create_app(path)) as client:
        assert options(client)[0]['trade_id'] == trade['trade_id']


def test_zerodha_single_subscription_retains_closed_then_unsubscribes(live):
    client, broker = live
    provider = client.app.state.market_data_provider
    provider.socket = type('Socket', (), {'send': AsyncMock()})()
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    client.portal.call(provider.refresh_subscriptions)
    client.portal.call(provider.handle_message, frame(256265, 24900))
    client.portal.call(provider.handle_message, frame(256265, 25000))
    trade, = client.get('/trades').json()
    assert options(client)[0]['entry_price'] == 120
    assert provider.subscribed == {256265, 10002}
    sends = [json.loads(call.args[0]) for call in provider.socket.send.call_args_list]
    assert sum(m['a'] == 'subscribe' and m['v'] == [10002] for m in sends) == 1
    client.portal.call(provider.refresh_subscriptions)
    assert provider.socket.send.call_count == len(sends)
    client.portal.call(provider.handle_message, frame(10002, 100))
    assert options(client)[0]['status'] == 'CLOSED' and provider.subscribed == {256265, 10002}
    client.portal.call(provider.handle_message, frame(10002, 115))
    assert options(client)[0]['current_ltp'] == 115
    broker.ltp.assert_awaited_once()
    provider.subscribed = set()
    client.portal.call(provider.refresh_subscriptions)
    assert provider.subscribed == {256265, 10002}  # Closed membership survives socket reconnect.
    assert client.delete('/watchlist/options/' + trade['option_symbol']).status_code == 204
    client.portal.call(provider.refresh_subscriptions)
    assert provider.subscribed == {256265}
    assert json.loads(provider.socket.send.call_args_list[-1].args[0]) == {'a': 'unsubscribe', 'v': [10002]}
    provider.subscribed = set()
    client.portal.call(provider.refresh_subscriptions)
    assert provider.subscribed == {256265}


def test_trade_entry_publishes_watchlist_without_browser_refresh(client):
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    tick(client, 'NIFTY', 24900)
    with client.websocket_connect('/ws/market') as socket:
        tick(client, 'NIFTY', 25000)
        item, = [event['data'] for event in until_price(socket) if event['type'] == 'OPTION_WATCHLIST_UPDATED']
        assert item == options(client)[0]
        assert item['status'] == 'ACTIVE'
        tick(client, 'NIFTY', 25000)
        assert not any(event['type'] == 'OPTION_WATCHLIST_UPDATED' for event in until_price(socket))
