from active_level_fixture import create_active_level, create_active_record
import asyncio
import hashlib
import json
import struct
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market_data import PriceTick
from app.settings import TradeSettings
from app.zerodha.connector import KiteConnector, MarketSettings
from app.zerodha.instruments import ZerodhaInstrumentService, normalize
from app.zerodha.provider import ZerodhaMarketDataProvider


def master():
    rows = [dict(instrument_token=256265, exchange_token=1001, tradingsymbol='NIFTY 50', name='NIFTY 50',
                 exchange='NSE', segment='INDICES', instrument_type='EQ', strike=0, expiry='', lot_size=0, tick_size=0.05),
            dict(instrument_token=260105, exchange_token=1002, tradingsymbol='NIFTY BANK', name='NIFTY BANK',
                 exchange='NSE', segment='INDICES', instrument_type='EQ', strike=0, expiry='', lot_size=0, tick_size=0.05)]
    for index, strike in enumerate([24950, 25000, 25050]):
        rows.append(dict(instrument_token=10000+index, exchange_token=2000+index,
            tradingsymbol=f'NIFTY269212{strike}PE', name='NIFTY', exchange='NFO', segment='NFO-OPT',
            instrument_type='PE', strike=strike, expiry='2026-09-21', lot_size=65, tick_size=0.05))
    rows.append(dict(instrument_token=265, exchange_token=1, tradingsymbol='SENSEX', name='SENSEX',
        exchange='BSE', segment='INDICES', instrument_type='EQ', strike=0, expiry='', lot_size=0, tick_size=0.05))
    for index, strike in enumerate([79900, 80000, 80100]):
        for option_type in ('CE', 'PE'):
            rows.append(dict(instrument_token=20000 + index * 2 + (option_type == 'PE'),
                exchange_token=3000 + index * 2 + (option_type == 'PE'),
                tradingsymbol=f'SENSEX26921{strike}{option_type}', name='SENSEX', exchange='BFO', segment='BFO-OPT',
                instrument_type=option_type, strike=strike, expiry='2026-09-21', lot_size=37, tick_size=0.05))
    return rows


class FakeConnector:
    authenticated = False
    def __init__(self):
        self.instruments = AsyncMock(return_value=master())
        self.ltp = AsyncMock(return_value=120)
        self.close = AsyncMock()
        self.exchange = AsyncMock()
    def login_url(self):
        return 'https://kite.zerodha.com/connect/login?v=3&api_key=test'
    def websocket_url(self):
        return 'wss://mock.invalid'


@pytest.fixture
def live(tmp_path):
    broker = FakeConnector()
    # No network-capable socket can be created by these app tests.
    def forbidden_socket(*args, **kwargs):
        raise AssertionError('Unexpected socket connection')
    app = create_app(tmp_path / 'data.sqlite3', market_settings=MarketSettings(market_data_mode='ZERODHA'),
                     kite_connector=broker, socket_factory=forbidden_socket)
    with TestClient(app) as client:
        assert client.post('/zerodha/instruments/sync').status_code == 200
        yield client, broker


def frame(token, price):
    return struct.pack('!HHII', 1, 8, token, int(price * 100))


def test_normalization_and_lookup(live):
    client, _ = live
    service = client.app.state.zerodha_instruments
    assert service.index('NIFTY').instrument_token == 256265
    assert service.index('BANKNIFTY').instrument_token == 260105
    contract = service.contracts('NIFTY')[0]
    assert service.option(contract.symbol).exchange == 'NFO'
    assert contract.lot_size == 65
    assert service.strike_step('NIFTY') == 50
    assert service.by_token(10000).exchange_token == 2000
    assert normalize(dict(master()[0], tradingsymbol='UNRELATED')) is None
    assert normalize(dict(master()[2], name='FINNIFTY')) is None
    reloaded = ZerodhaInstrumentService(client.app.state.database_path, FakeConnector())
    assert reloaded.records == service.records
    assert reloaded.last_sync == service.last_sync


def test_sensex_normalization_option_selection_and_cached_metadata(live):
    from datetime import date
    from app.option_selector import OptionSelector

    client, broker = live
    service = client.app.state.zerodha_instruments
    assert service.index('SENSEX').exchange == 'BSE'
    assert service.index('SENSEX').instrument_token == 265
    assert service.strike_step('SENSEX') == 100
    for direction, strike, option_type in [('FROM_ABOVE', 79900, 'CE'), ('FROM_BELOW', 80100, 'PE')]:
        selection = OptionSelector(service).select('SENSEX', 80000, direction, 1, date(2026, 9, 14))
        assert selection.status == 'SELECTED'
        assert selection.itm_strike == strike
        contract = service.option(selection.option_symbol)
        assert contract.exchange == 'BFO'
        assert contract.instrument_type == option_type
        assert contract.lot_size == 37  # Fixture metadata, not a hardcoded SENSEX lot size.
    reloaded = ZerodhaInstrumentService(client.app.state.database_path, broker)
    assert reloaded.contracts('SENSEX') == service.contracts('SENSEX')
    assert normalize(dict(master()[-1], exchange='NFO', segment='NFO-OPT')) is None
    assert normalize(dict(master()[-1], name='BANKEX')) is None

    # Prove the selector derives spacing, even for a different instrument master.
    rows = [dict(row, strike=80000 + (row['strike'] - 80000) * 2)
            if row['name'] == 'SENSEX' and row['instrument_type'] in ('CE', 'PE') else row
            for row in master()]
    broker.instruments.return_value = rows
    assert client.post('/zerodha/instruments/sync').status_code == 200
    assert service.strike_step('SENSEX') == 200
    selection = OptionSelector(service).select('SENSEX', 80000, 'FROM_BELOW', 1, date(2026, 9, 14))
    assert selection.status == 'SELECTED'
    assert selection.itm_strike == 80200


def test_sensex_live_ticks_open_paper_trade_with_bfo_quote(live):
    client, broker = live
    level = client.post('/levels', json=dict(instrument='SENSEX', price=80000, enabled=True)).json()
    provider = client.app.state.market_data_provider
    assert provider.required_tokens() == {265}
    provider.subscribed = {265}
    for price in (79900, 79929):
        client.portal.call(provider.handle_message, frame(265, price))
        assert client.get(f"/levels/{level['id']}").json()['status'] == 'PENDING_ARM'
    client.portal.call(provider.handle_message, frame(265, 79930))
    assert client.get('/signals').json() == []
    assert client.get(f"/levels/{level['id']}").json()['status'] == 'ACTIVE'
    client.portal.call(provider.handle_message, frame(265, 80000))
    trade, = client.get('/trades').json()
    assert trade['instrument'] == 'SENSEX'
    assert trade['trade_mode'] == 'PAPER'
    assert trade['quantity'] == 37
    assert trade['entry_price'] == 120
    broker.ltp.assert_awaited_once_with('BFO', trade['option_symbol'])
    assert provider.required_tokens() == {265, 20005}
    assert client.get(f"/levels/{level['id']}").json()['status'] == 'DISARMED'
    provider.subscribed = provider.required_tokens()
    client.portal.call(provider.handle_message, frame(20005, 100))
    assert client.get('/trades').json()[0]['exit_reason'] == 'STOP_LOSS'
    assert provider.required_tokens() == {265}


def test_failed_sync_preserves_previous_master(live):
    client, broker = live
    before = client.app.state.zerodha_instruments.records
    broker.instruments.return_value = [dict(master()[0], instrument_token='bad')]
    assert client.post('/zerodha/instruments/sync').status_code == 502
    assert client.app.state.zerodha_instruments.records == before
    assert client.get('/connection').json()['instrument_sync_status'] == 'FAILED'


def test_normalized_ticks_and_shared_pipeline(live):
    client, broker = live
    app = client.app
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    provider = app.state.market_data_provider
    assert isinstance(provider, ZerodhaMarketDataProvider)
    provider.subscribed = {256265}
    asyncio.run(provider.handle_message(frame(256265, 24900)))
    asyncio.run(provider.handle_message(frame(256265, 25000)))
    assert app.state.level_monitor.recent_events()[0].current_price == 25000
    assert client.get('/signals').json()[0]['valid'] is True
    trade, = client.get('/trades').json()
    assert trade['trade_mode'] == 'PAPER'
    assert trade['entry_price'] == 120
    assert trade['quantity'] == 65
    broker.ltp.assert_awaited_once()
    assert provider.required_tokens() == {256265, 10002}
    assert client.post('/simulation/tick', json=dict(instrument='NIFTY', price=25001)).status_code == 409
    provider.subscribed = provider.required_tokens()
    asyncio.run(provider.handle_message(frame(10002, 100)))
    assert client.get('/trades').json()[0]['exit_reason'] == 'STOP_LOSS'
    assert provider.required_tokens() == {256265}
    broker.ltp.assert_awaited_once()  # Ongoing option ticks never REST-poll.


def test_subscriptions_and_resubscribe(live):
    client, _ = live
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    create_active_level(client, json=dict(instrument='BANKNIFTY', price=51000, enabled=False))
    provider = client.app.state.market_data_provider
    socket = type('Socket', (), {'send': AsyncMock()})()
    provider.socket = socket
    asyncio.run(provider.refresh_subscriptions())
    assert json.loads(socket.send.call_args_list[0].args[0]) == {'a': 'subscribe', 'v': [256265]}
    asyncio.run(provider.refresh_subscriptions())
    assert socket.send.await_count == 2  # subscribe + mode, no redundant calls
    provider.subscribed = set()  # New connection always starts with an empty sent set.
    asyncio.run(provider.refresh_subscriptions())
    assert socket.send.await_count == 4
    client.delete('/levels/1')
    asyncio.run(provider.refresh_subscriptions())
    assert json.loads(socket.send.call_args.args[0]) == {'a': 'unsubscribe', 'v': [256265]}
    provider.socket = None


@pytest.mark.parametrize('token,price', [(999, 10), (256265, float('nan')), (256265, -1), (256265, 0),
                                        (True, 10), (256265, True), ('256265', 10)])
def test_invalid_normalized_ticks(live, token, price):
    assert live[0].app.state.market_data_provider.normalize_tick(token, price) is None


@pytest.mark.parametrize('message', [b'\x00', b'\x00\x01', b'\x00\x01\x00\xff', 'malformed text',
                                    frame(999, 10), frame(256265, 25000)+b'x'])
def test_invalid_frames_do_not_enter_strategy(live, message):
    provider = live[0].app.state.market_data_provider
    provider.subscribed = {256265}
    consumer = AsyncMock()
    provider.consumer = consumer
    asyncio.run(provider.handle_message(message))
    consumer.assert_not_awaited()


def test_simulated_mode_unchanged(client):
    assert client.get('/connection').json()['market_data_mode'] == 'SIMULATED'
    assert client.post('/simulation/tick', json=dict(instrument='NIFTY', price=25000)).status_code == 200
    assert client.get('/zerodha/login-url').status_code == 409


@pytest.mark.parametrize('mode', ['LIVE', 'BACKTEST'])
def test_live_mode_rejected_before_broker_access(tmp_path, mode):
    with pytest.raises(ValueError, match='requires PAPER'):
        with TestClient(create_app(tmp_path/'db', market_settings=MarketSettings(market_data_mode='ZERODHA'),
                                  trade_settings=TradeSettings(trade_mode=mode))):
            pass


def test_authentication_protocol_and_secret_redaction():
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == '/session/token':
            return httpx.Response(200, json={'data': {'access_token': 'private-token'}})
        return httpx.Response(403)
    async def check():
        settings = MarketSettings(api_key='key', api_secret='private-secret')
        connector = KiteConnector(settings, httpx.AsyncClient(base_url='https://mock.invalid', transport=httpx.MockTransport(respond)))
        assert 'api_key=key' in connector.login_url()
        await connector.exchange('request-token')
        assert connector.authenticated
        expected = hashlib.sha256(b'keyrequest-tokenprivate-secret').hexdigest()
        assert expected in requests[0].content.decode()
        assert 'private-secret' not in repr(settings)
        assert 'private-token' not in repr(connector._token)
        with pytest.raises(ValueError, match='expired'):
            await connector.ltp('NFO', 'symbol')
        assert not connector.authenticated
        await connector.close()
    asyncio.run(check())


def test_missing_entry_quote_cannot_create_trade(live):
    client, broker = live
    broker.ltp.return_value = None
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    provider = client.app.state.market_data_provider
    asyncio.run(provider.publish(PriceTick(instrument='NIFTY', price=24900)))
    asyncio.run(provider.publish(PriceTick(instrument='NIFTY', price=25000)))
    assert client.get('/trades').json() == []
    assert client.get('/trade-entry-results').json()[0]['failure_reason'] == 'OPTION_PRICE_UNAVAILABLE'


def test_reconnect_loop_resubscribes(live):
    client, broker = live
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    original = client.app.state.market_data_provider
    connections = []
    async def check():
        reached = asyncio.Event()
        class Socket:
            def __init__(self): self.sent = []
            async def send(self, message): self.sent.append(json.loads(message))
            async def recv(self):
                if len(connections) == 1:
                    raise OSError('disconnected')
                reached.set()
                await asyncio.Future()
        @asynccontextmanager
        async def factory(*args, **kwargs):
            socket = Socket()
            connections.append(socket)
            yield socket
        broker.authenticated = True
        provider = ZerodhaMarketDataProvider(AsyncMock(), original.instruments, broker,
            original.levels, original.trades, factory)
        task = asyncio.create_task(provider.run())
        try:
            await asyncio.wait_for(reached.wait(), timeout=3)
            assert provider.reconnect_count == 1
            assert provider.status == 'CONNECTED'
            assert len(connections) == 2
            assert connections[0].sent == connections[1].sent
            assert connections[1].sent[0] == {'a': 'subscribe', 'v': [256265]}
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            broker.authenticated = False
    asyncio.run(check())


def test_synced_indices_available_without_any_levels(live):
    client, _ = live
    assert client.get('/levels').json() == []
    assert client.get('/connection').json()['available_instruments'] == ['NIFTY', 'BANKNIFTY', 'SENSEX']


def test_continuous_socket_prices_do_not_poll_rest_and_expose_metrics(live):
    client, broker = live
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    provider = client.app.state.market_data_provider
    provider.subscribed = {256265}
    provider.set_status('CONNECTED')
    with client.websocket_connect('/ws/market') as socket:
        for price in [24900, 24901, 24902]:
            client.portal.call(provider.handle_message, frame(256265, price))
            event = socket.receive_json()
            assert event['type'] == 'MARKET_PRICE_UPDATED'
            assert event['data']['price'] == price
        broker.ltp.assert_not_awaited()
        assert provider.ticks_received == 3
        assert provider.last_tick_at
        result = client.get('/connection').json()
        assert result['ticks_received'] == 3
        assert result['subscribed_instrument_count'] == 1
        assert result['last_tick_at'] == provider.last_tick_at
        client.portal.call(provider.set_status, 'DISCONNECTED')
        status = socket.receive_json()
        assert status['type'] == 'ZERODHA_CONNECTION_STATUS'
        assert status['data']['connection_status'] == 'DISCONNECTED'
        assert 'api_key' not in json.dumps(status)
        assert 'access_token' not in json.dumps(status)
