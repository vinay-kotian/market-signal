"""Read-only charts use recorded observations, preserving execution relationships."""
import asyncio
from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.chart_data import CandleRepository, parse_timestamp
from app.database import connect, initialize_database
from app.main import create_app
from app.settings import TradeSettings
from app.zerodha.connector import KiteConnector, MarketSettings
from test_position_monitor import enter, tick
from test_live_feed import until_price
from test_zerodha import live

DAY = '2026-09-14'


def get(client, symbol, kind='events', day=DAY):
    response = client.get(f'/instruments/{symbol}/{kind}?date={day}')
    assert response.status_code == 200, response.text
    return response.json()


def test_received_candles_ohlc_gaps_socket_and_restart(tmp_path):
    path = tmp_path / 'charts.db'
    now = [parse_timestamp('2026-09-14T03:45:10Z')]
    with TestClient(create_app(path, clock=lambda: now[0])) as client:
        with client.websocket_connect('/ws/market') as socket:
            for price in [25000, 25020, 24980, 25010]:
                tick(client, 'NIFTY', price)
                event = until_price(socket)[-1]
            candle = event['data']['candle']
            assert [candle[field] for field in ['open', 'high', 'low', 'close']] == [25000, 25020, 24980, 25010]
            assert candle['time'] == int(parse_timestamp('2026-09-14T03:45:00Z').timestamp())
            assert candle['volume'] is None
            now[0] = parse_timestamp('2026-09-14T03:47:11Z')
            tick(client, 'NIFTY', 25015)
            until_price(socket)
        before = get(client, 'NIFTY', 'candles')['candles']
        assert len(before) == 2  # No invented 09:16 candle.
        now[0] = parse_timestamp('2026-09-14T10:00:00Z')  # 15:30 is outside candle session.
        tick(client, 'NIFTY', 999)
        assert get(client, 'NIFTY', 'candles')['candles'] == before
    with TestClient(create_app(path, clock=lambda: now[0])) as client:
        assert get(client, 'NIFTY', 'candles')['candles'] == before
        assert get(client, 'NIFTY', 'candles', '2026-09-13')['candles'] == []


def test_actual_arm_trigger_signal_and_snapshot_survive_level_edit_delete(client):
    tick(client, 'NIFTY', 24900)
    level = client.post('/levels', json=dict(instrument='NIFTY', price=25000, enabled=True)).json()
    assert level['status'] == 'ACTIVE'
    tick(client, 'NIFTY', 25000)
    records = get(client, 'NIFTY')['events']
    assert [row['event_type'] for row in records] == ['LEVEL_ARMED', 'LEVEL_TRIGGERED', 'SIGNAL_GENERATED', 'TRADE_TRIGGERED']
    touch = next(row for row in records if row['event_type'] == 'LEVEL_TRIGGERED')
    signal = client.get('/signals').json()[0]
    assert touch['signal_id'] == signal['id'] and parse_timestamp(touch['timestamp']) == parse_timestamp(signal['timestamp'])
    assert touch['price'] == 25000 and touch['previous_price'] == 24900 and touch['trigger_kind'] == 'TOUCH'
    assert touch['direction'] == 'FROM_BELOW'
    assert client.delete(f"/levels/{level['id']}").status_code == 204
    assert get(client, 'NIFTY')['events'] == records


def test_pending_arming_is_saved_only_on_actual_transition_and_rejected_cross(client):
    level = client.post('/levels', json=dict(instrument='NIFTY', price=25000, enabled=True)).json()
    tick(client, 'NIFTY', 24999)
    assert get(client, 'NIFTY')['events'] == []
    tick(client, 'NIFTY', 24900)
    tick(client, 'NIFTY', 25001)
    records = get(client, 'NIFTY')['events']
    assert sum(row['event_type'] == 'LEVEL_ARMED' for row in records) == 1
    assert next(row for row in records if row['event_type'] == 'LEVEL_TRIGGERED')['trigger_kind'] == 'CROSS'
    assert all(row['level'] == level['price'] for row in records)
    # Independent instrument, first tick arms but never triggers; rejection is
    # tested by a persisted first touch with insufficient directional history.
    with connect(client.app.state.database_path) as c:
        c.execute("INSERT INTO signals(trigger_id,level_id,instrument,level,trigger_price,direction,approach_distance,valid,rejection_reason,timestamp) VALUES(999,999,'BANKNIFTY',51000,51000,NULL,NULL,0,'INSUFFICIENT_HISTORY','2026-09-14T10:00:03+05:30')")
    rejected, = get(client, 'BANKNIFTY')['events']
    assert rejected['event_type'] == 'SIGNAL_REJECTED' and rejected['rejection_reason'] == 'INSUFFICIENT_HISTORY'


def test_every_execution_and_protection_event_is_linked(client):
    trade = enter(client)
    symbol = trade['option_symbol']
    tick(client, symbol, 120)
    tick(client, symbol, 108)
    first = get(client, symbol)['events']
    types = {event['event_type'] for event in first}
    assert {'TRADE_ENTRY', 'TRADE_EXIT', 'STOP_LOSS_HIT', 'TRAILING_STOP_UPDATED', 'PROFIT_LOCK_ACTIVATED'} <= types
    for event in first:
        assert event['trade_id'] == trade['trade_id'] and event['signal_id'] == trade['signal_id']
        assert event['option_symbol'] == symbol and event['quantity'] == trade['quantity']
    entry = next(event for event in first if event['event_type'] == 'TRADE_ENTRY')
    assert entry['price'] == 100 and entry['initial_stop_loss'] == 90 and entry['index_price'] == 25000
    exit = next(event for event in first if event['event_type'] == 'TRADE_EXIT')
    assert exit['price'] == 108 and exit['realised_pnl'] == 80 and exit['realised_pnl_percentage'] == 8
    assert exit['exit_reason'] == 'TRAILING_STOP_LOSS' and exit['duration_seconds'] == 0
    trailing = next(event for event in first if event['event_type'] == 'TRAILING_STOP_UPDATED')
    assert trailing['previous_stop'] is not None and trailing['current_stop'] == 109.2
    # Rearm, then enter the same contract again. Every execution remains visible.
    tick(client, symbol, 110)
    tick(client, 'NIFTY', 24900)
    tick(client, 'NIFTY', 25000)
    tick(client, symbol, 90)
    trades = get(client, symbol, 'trades')['trades']
    assert len(trades) == 2 and all(trade['trade_mode'] == 'PAPER' for trade in trades)
    events = get(client, symbol)['events']
    assert len([event for event in events if event['event_type'] == 'TRADE_ENTRY']) == 2
    assert len([event for event in events if event['event_type'] == 'TRADE_EXIT']) == 2


def test_backtest_and_reconstructed_protection_never_appear(client):
    trade = enter(client)
    tick(client, trade['option_symbol'], 120)
    with connect(client.app.state.database_path) as c:
        c.execute("UPDATE trade_events SET reconstructed=1 WHERE event_type!='POSITION_OPENED'")
    assert [event['event_type'] for event in get(client, trade['option_symbol'])['events']] == ['TRADE_ENTRY']
    with connect(client.app.state.database_path) as c:
        c.execute("UPDATE trades SET trade_mode='BACKTEST'")
    assert get(client, 'NIFTY', 'trades')['trades'] == []
    assert get(client, 'NIFTY')['events'] == []
    assert client.get(f"/instruments/{trade['option_symbol']}/events?date={DAY}").status_code == 404


def test_recorded_legacy_breakeven_is_shown_without_inventing_updates(tmp_path):
    with TestClient(create_app(tmp_path / 'legacy.db', trade_settings=TradeSettings(stop_strategy='LEGACY'))) as client:
        trade = enter(client)
        assert {event['event_type'] for event in get(client, trade['option_symbol'])['events']} == {'TRADE_ENTRY'}
        tick(client, trade['option_symbol'], 110)
        events = get(client, trade['option_symbol'])['events']
        breakeven, = [event for event in events if event['event_type'] == 'BREAKEVEN_PROTECTION_ACTIVATED']
        assert breakeven['previous_stop'] == 90 and breakeven['current_stop'] == 100


def test_ist_date_and_precise_timestamps_preserved_after_restart(tmp_path):
    path = tmp_path / 'exact.db'
    with TestClient(create_app(path)) as client:
        trade = enter(client)
        with connect(path) as c:
            c.execute("UPDATE trades SET entry_time='2026-09-13T18:31:03.123456+00:00'")
            c.execute("UPDATE signals SET timestamp='2026-09-13T18:31:02.234567+00:00'")
            c.execute("UPDATE chart_events SET timestamp='2026-09-13T18:31:02.234567+00:00'")
        assert get(client, 'NIFTY', day='2026-09-13')['events'] == []
        tick(client, trade['option_symbol'], 90)
        entry = next(event for event in get(client, trade['option_symbol'])['events'] if event['event_type'] == 'TRADE_ENTRY')
        assert parse_timestamp(entry['timestamp']).microsecond == 123456
        before = get(client, trade['option_symbol'])['events']
    with TestClient(create_app(path)) as client:
        assert get(client, trade['option_symbol'])['events'] == before


def test_failed_signal_transaction_does_not_leave_trigger_snapshot(client, monkeypatch):
    trade = enter(client)
    tick(client, trade['option_symbol'], 90)
    tick(client, 'NIFTY', 24900)
    before = get(client, 'NIFTY')['events']
    def fail(*args, **kwargs):
        raise ValueError('write failed')
    monkeypatch.setattr(client.app.state.option_repository, 'save', fail)
    with pytest.raises(ValueError, match='write failed'):
        client.post('/simulation/tick', json=dict(instrument='NIFTY', price=25000))
    assert get(client, 'NIFTY')['events'] == before


def test_lazy_historical_cache_token_alias_no_new_subscriptions(live):
    client, broker = live
    broker.authenticated = True
    broker.historical_candles = AsyncMock(return_value=[['2026-09-11T09:15:00+05:30', 25000, 25020, 24990, 25010, 42]])
    provider = client.app.state.market_data_provider
    before = provider.required_tokens()
    assert broker.historical_candles.await_count == 0
    first = get(client, '256265', 'candles', '2026-09-11')
    assert first['instrument']['symbol'] == 'NIFTY' and first['candles'][0]['origin'] == 'ZERODHA_HISTORY'
    assert get(client, 'NIFTY', 'candles', '2026-09-11')['candles'] == first['candles']
    assert broker.historical_candles.await_count == 1 and provider.required_tokens() == before
    broker.authenticated = False
    assert get(client, 'NIFTY', 'candles', '2026-09-11')['candles'] == first['candles']


def test_missing_auth_failed_history_and_empty_history_are_honest(live):
    client, broker = live
    assert 'login required' in get(client, 'NIFTY', 'candles')['message']
    broker.authenticated = True
    broker.historical_candles = AsyncMock(side_effect=ValueError('unavailable'))
    assert 'unavailable from Zerodha' in get(client, 'NIFTY', 'candles')['message']
    broker.historical_candles = AsyncMock(return_value=[])
    result = get(client, 'NIFTY', 'candles', '2026-09-11')
    assert result['candles'] == [] and 'No candles' in result['message']
    get(client, 'NIFTY', 'candles', '2026-09-11')
    assert broker.historical_candles.await_count == 1


def test_expired_option_uses_persisted_identity_not_reused_master_token(client):
    trade = enter(client)
    tick(client, trade['option_symbol'], 110)
    with connect(client.app.state.database_path) as c:
        c.execute("UPDATE trades SET expiry='2026-09-13'")
    state = client.app.state
    state.market_settings.market_data_mode = 'ZERODHA'
    state.kite = type('Broker', (), {'authenticated': True, 'historical_candles': AsyncMock()})()
    result = get(client, trade['option_symbol'], 'candles')
    assert result['candles'][0]['close'] == 110
    assert 'safe historical token' in result['message']
    state.kite.historical_candles.assert_not_awaited()
    state.kite = None  # This fake does not own a client requiring lifespan cleanup.


def test_source_isolation_and_broker_cache_preserves_live_current_minute(tmp_path):
    path = tmp_path / 'source.db'
    initialize_database(path)
    sim = CandleRepository(path, 'SIMULATED')
    live = CandleRepository(path, 'ZERODHA')
    now = parse_timestamp('2026-09-14T10:00:10+05:30')
    sim.observe('NIFTY', 999, now)
    live.observe('NIFTY', 25005, now)
    assert live.list('NIFTY', date(2026, 9, 14))[0]['close'] == 25005
    live.cache('NIFTY', date(2026, 9, 14), [['2026-09-14T10:00:00+05:30', 25000, 25020, 24990, 25010, 10]], now)
    assert live.list('NIFTY', date(2026, 9, 14))[0]['close'] == 25005
    with pytest.raises(ValueError):
        live.cache('NIFTY', date(2026, 9, 14), [['2026-09-14T10:00:00+05:30', 10, 9, 11, 10, 0]], now)
    assert sim.list('NIFTY', date(2026, 9, 14))[0]['close'] == 999


def test_date_interval_identity_validation(client):
    for query in ['date=bad', 'date=2026-09-14&interval=day', 'date=2026-09-15']:
        assert client.get('/instruments/NIFTY/candles?' + query).status_code == 422
    assert client.get('/instruments/UNKNOWN/candles?date=' + DAY).status_code == 404
    assert get(client, 'SENSEX', 'candles')['candles'] == []


def test_connector_history_is_read_only_and_uses_local_session_times():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'data': {'candles': []}})
    connector = KiteConnector(MarketSettings(api_key='key', access_token='token'),
                              httpx.AsyncClient(base_url='https://api.kite.trade', transport=httpx.MockTransport(handle)))
    async def exercise():
        assert await connector.historical_candles(256265, parse_timestamp('2026-09-14T09:15:00+05:30'), parse_timestamp('2026-09-14T15:30:00+05:30')) == []
        request, = seen
        assert request.method == 'GET' and request.url.path == '/instruments/historical/256265/minute'
        assert request.url.params['from'] == '2026-09-14 09:15:00'
        assert request.url.params['continuous'] == '0'
        await connector.close()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(exercise())
    finally:
        loop.close()
