from active_level_fixture import create_active_level, create_active_record
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.live_feed import WebSocketHub
from app.main import create_app
from app.market_data import PriceTick


def tick(client, price, instrument='NIFTY'):
    assert client.post('/simulation/tick', json=dict(instrument=instrument, price=price)).status_code == 200


def until_price(socket):
    events = []
    for _ in range(30):
        event = socket.receive_json()
        events.append(event)
        if event['type'] == 'MARKET_PRICE_UPDATED':
            return events
    pytest.fail('No price event')


def test_accept_broadcast_multiple_clients_and_cleanup(client):
    hub = client.app.state.websocket_hub
    with client.websocket_connect('/ws/market') as first:
        with client.websocket_connect('/ws/market') as second:
            assert len(hub.clients) == 2
            tick(client, 24900)
            a, b = first.receive_json(), second.receive_json()
            assert a == b
            assert a['type'] == 'MARKET_PRICE_UPDATED'
            assert a['data']['price'] == 24900
            assert a['data']['change'] is None
            assert datetime.fromisoformat(a['timestamp']).tzinfo
        # Synchronize with the endpoint finalizer.
        client.portal.call(asyncio.sleep, 0.01)
        assert len(hub.clients) == 1
        tick(client, 24910)
        assert first.receive_json()['data']['change'] == 10
    client.portal.call(asyncio.sleep, 0.01)
    assert len(hub.clients) == 0


def test_committed_strategy_events_and_stops(client):
    id = create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True)).json()['id']
    with client.websocket_connect('/ws/market') as socket:
        tick(client, 24900)
        until_price(socket)
        tick(client, 25000)
        events = until_price(socket)
        kinds = {event['type'] for event in events}
        assert {'LEVEL_TRIGGERED', 'LEVEL_DISARMED', 'SIGNAL_CREATED', 'TRADE_OPENED',
                'OPTION_SELECTION_CREATED', 'TRADE_ENTRY_RESULT'} <= kinds
        trade = next(event['data'] for event in events if event['type'] == 'TRADE_OPENED')
        assert trade == client.get('/trades').json()[0]
        tick(client, 120, trade['option_symbol'])
        updated = until_price(socket)
        assert any(e['type'] == 'STOP_UPDATED' and e['data']['current_stop_loss'] == 108 for e in updated)
        tick(client, 108, trade['option_symbol'])
        closed = until_price(socket)
        assert any(e['type'] == 'TRADE_CLOSED' and e['data']['status'] == 'CLOSED' for e in closed)
        tick(client, 25050)
        rearmed = until_price(socket)
        assert any(e['type'] == 'LEVEL_REARMED' and e['data']['level']['id'] == id for e in rearmed)
        tick(client, 25050)
        assert [e['type'] for e in until_price(socket)] == ['MARKET_PRICE_UPDATED']


def test_market_close_without_tick_pushes_exit(tmp_path):
    now = [datetime(2026, 9, 14, 4, 30, tzinfo=timezone.utc)]
    with TestClient(create_app(tmp_path / 'db', clock=lambda: now[0])) as client:
        create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
        tick(client, 24900)
        tick(client, 25000)
        with client.websocket_connect('/ws/market') as socket:
            now[0] = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
            client.portal.call(client.app.state.market_close.check)
            event = socket.receive_json()
            assert event['type'] == 'TRADE_CLOSED'
            assert event['data']['exit_reason'] == 'MARKET_CLOSING_EXIT'


def test_rest_reconnect_snapshot_and_cross_client_crud(client):
    tick(client, 24900)
    with client.websocket_connect('/ws/market') as socket:
        assert client.get('/connection').json()['prices'] == {'NIFTY': 24900}
        level = client.post('/levels', json=dict(instrument='NIFTY', price=25000, enabled=True)).json()
        assert socket.receive_json()['data']['level'] == level
        client.delete(f"/levels/{level['id']}")
        assert socket.receive_json()['type'] == 'LEVEL_DELETED'
    tick(client, 24910)  # Disconnected browsers recover this from REST.
    with client.websocket_connect('/ws/market') as socket:
        assert client.get('/connection').json()['prices']['NIFTY'] == 24910
        tick(client, 24920)
        assert socket.receive_json()['data']['price'] == 24920


def test_cross_origin_rejected_and_proxy_root_supported(tmp_path):
    app = create_app(tmp_path / 'db')
    app.root_path = '/api'
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws/market', headers={'origin': 'https://untrusted.invalid'}):
                pass
        with client.websocket_connect('/ws/market', headers={'origin': 'http://testserver'}) as socket:
            tick(client, 25000)
            assert socket.receive_json()['type'] == 'MARKET_PRICE_UPDATED'


def test_slow_browser_buffer_is_bounded():
    hub = WebSocketHub(capacity=1)
    queue = asyncio.Queue(maxsize=1)
    hub.clients.add(queue)
    hub.publish('TRADE_OPENED', {})
    hub.publish('TRADE_CLOSED', {})
    assert queue.qsize() == 1
    assert queue.get_nowait() is None
    assert not hub.clients


def test_rollback_emits_no_trade_or_level_event(client, monkeypatch):
    from app.level_repository import LevelRepository
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    tick(client, 24900)
    queue = asyncio.Queue(maxsize=256)
    client.app.state.websocket_hub.clients.add(queue)
    original = LevelRepository.change_status
    def fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError('write failed')
    monkeypatch.setattr(LevelRepository, 'change_status', fail)
    with pytest.raises(RuntimeError, match='write failed'):
        tick(client, 25000)
    assert queue.empty()
    assert client.get('/trades').json() == []
    client.app.state.websocket_hub.clients.discard(queue)


def test_backtest_does_not_broadcast_live_events(client):
    queue = asyncio.Queue(maxsize=256)
    client.app.state.websocket_hub.clients.add(queue)
    result = client.post('/backtests/run', json=dict(instrument='NIFTY', levels=[25000], fixture='nifty-demo'))
    assert result.status_code == 201
    assert result.json()['status'] == 'COMPLETED'
    assert queue.empty()
    assert client.get('/connection').json()['prices'] == {}
    client.app.state.websocket_hub.clients.discard(queue)
