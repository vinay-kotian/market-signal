import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from active_level_fixture import create_active_level
from app.database import connect
from app.main import create_app
from app.telegram_notifications import TelegramNotifications, TELEGRAM_URL
from app.trade_models import TradeEntry
from app.trade_repository import TradeRepository
from test_paper_report import add_trade


RUN_WORKER = TelegramNotifications.run


@pytest.fixture(autouse=True)
def park_worker(monkeypatch):
    # No test can reach the real Telegram channel. Delivery is driven explicitly
    # through MockTransport below, independently of the polling timer.
    async def parked(self):
        await asyncio.Event().wait()
    monkeypatch.setattr(TelegramNotifications, 'run', parked)


def enabled(client, value=True):
    response = client.put('/settings/telegram', json={'enabled': value})
    assert response.status_code == 200
    assert response.json()['enabled'] == value
    assert response.json()['url']


def rows(client):
    with connect(client.app.state.database_path) as connection:
        return [dict(row) for row in connection.execute('SELECT * FROM telegram_notifications ORDER BY trade_id')]


def mock_sender(client, handler):
    service = client.app.state.telegram_notifications
    client.portal.call(service.client.aclose)
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10)
    return service


def test_defaults_off_and_toggle_persists_across_restart(client):
    assert client.get('/settings/telegram').json() == {'enabled': False, 'url': TELEGRAM_URL}
    add_trade(client)
    assert rows(client) == []
    enabled(client)
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert restarted.get('/settings/telegram').json() == {'enabled': True, 'url': TELEGRAM_URL}
        enabled(restarted, False)
    assert client.get('/settings/telegram').json() == {'enabled': False, 'url': TELEGRAM_URL}


@pytest.mark.parametrize('payload', [{}, {'enabled': 'true'}, {'enabled': 1}, {'enabled': None},
                                      {'enabled': True, 'unknown': 'https://example.com'}])
def test_invalid_settings_rejected(client, payload):
    assert client.put('/settings/telegram', json=payload).status_code == 422
    assert client.get('/settings/telegram').json() == {'enabled': False, 'url': TELEGRAM_URL}


@pytest.mark.parametrize('url', ['', 'bad', 'ftp://relay.example/api', '/relative', None, 42])
def test_invalid_urls_do_not_change_saved_settings(client, url):
    assert client.put('/settings/telegram', json={'enabled': True, 'url': url}).status_code == 422
    assert client.get('/settings/telegram').json() == {'enabled': False, 'url': TELEGRAM_URL}


def test_url_persists_and_toggle_only_update_preserves_it(client):
    url = 'https://relay.example/api/telegram'
    response = client.put('/settings/telegram', json={'enabled': False, 'url': '  ' + url + '\u00a0'})
    assert response.status_code == 200
    assert response.json() == {'enabled': False, 'url': url}
    enabled(client)
    assert client.get('/settings/telegram').json() == {'enabled': True, 'url': url}
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert restarted.get('/settings/telegram').json() == {'enabled': True, 'url': url}


def test_legacy_settings_migration_keeps_enabled_state(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with connect(path) as connection:
        connection.execute('CREATE TABLE telegram_settings (id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL)')
        connection.execute('INSERT INTO telegram_settings VALUES (1, 1)')
    with TestClient(create_app(path)) as client:
        assert client.get('/settings/telegram').json() == {'enabled': True, 'url': TELEGRAM_URL}


def test_pending_delivery_uses_configured_url(client):
    enabled(client)
    add_trade(client)
    url = 'https://relay.example/new-telegram'
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'sent': True})

    service = mock_sender(client, handler)
    assert client.put('/settings/telegram', json={'enabled': True, 'url': url}).status_code == 200
    assert client.portal.call(service.deliver_next)
    assert str(requests[0].url) == url


def test_entry_message_details_and_duplicate_saves(client):
    enabled(client)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'sent': True, 'message_id': 300})

    service = mock_sender(client, handler)
    trade = add_trade(client)
    client.app.state.trade_repository.save(TradeEntry(**trade.model_dump()))
    assert len(rows(client)) == 1
    assert requests == []  # No HTTP inside save().
    assert client.portal.call(service.deliver_next)
    assert not client.portal.call(service.deliver_next)
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == TELEGRAM_URL
    assert request.method == 'POST'
    assert request.headers['content-type'] == 'application/json'
    payload = json.loads(request.content)
    assert list(payload) == ['message']
    for text in [f'Trade #{trade.trade_id}', 'Index: NIFTY', 'Index level touched: 25,000.00',
                 f'Option: {trade.option_symbol}', 'Entry premium: ₹100.00',
                 'Quantity: 10 (1 lots × 10)', 'Initial stop premium: ₹90.00',
                 '14 Sep 2026 10:00:00 IST', 'FROM BELOW', 'Expiry 2026-09-17']:
        assert text in payload['message']
    assert rows(client)[0]['status'] == 'SENT'
    assert rows(client)[0]['attempts'] == 1


def test_backtests_never_enqueue_or_send(client):
    trade = add_trade(client)
    enabled(client)
    repository = TradeRepository(client.app.state.database_path, mode='BACKTEST')
    repository.save(TradeEntry(**{**trade.model_dump(), 'trade_mode': 'BACKTEST',
                                  'signal_id': 2, 'option_selection_id': 2}))
    assert rows(client) == []


def test_rollback_cannot_notify(client):
    template = add_trade(client)
    enabled(client)
    with pytest.raises(RuntimeError), connect(client.app.state.database_path) as connection:
        client.app.state.trade_repository.save(TradeEntry(**{
            **template.model_dump(), 'signal_id': 2, 'option_selection_id': 2,
        }), connection)
        raise RuntimeError('rollback fixture')
    assert rows(client) == []
    assert len(client.get('/trades').json()) == 1


def test_disabled_pending_alerts_cancel_and_do_not_replay(client):
    enabled(client)
    add_trade(client)
    enabled(client, False)
    add_trade(client, 2)
    enabled(client)
    assert len(rows(client)) == 1
    assert rows(client)[0]['status'] == 'CANCELLED'
    assert not client.portal.call(client.app.state.telegram_notifications.deliver_next)


def test_pending_alert_survives_restart_and_sent_alert_does_not_replay(client):
    enabled(client)
    add_trade(client)
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        service = mock_sender(restarted, lambda request: httpx.Response(200, json={'sent': True}))
        assert restarted.portal.call(service.deliver_next)
        assert rows(restarted)[0]['status'] == 'SENT'
    with TestClient(create_app(client.app.state.database_path)) as restarted:
        assert not restarted.portal.call(restarted.app.state.telegram_notifications.deliver_next)


@pytest.mark.parametrize('failure', ['http', 'timeout', 'sent_false', 'invalid_json'])
def test_failure_retries_are_bounded_and_preserve_trade(client, failure):
    enabled(client)
    trade = add_trade(client)
    before = client.get(f'/trades/{trade.trade_id}').json()
    requests = []

    def handler(request):
        requests.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('mock timeout', request=request)
        if failure == 'http':
            return httpx.Response(500, text='relay unavailable')
        if failure == 'invalid_json':
            return httpx.Response(200, text='not json')
        return httpx.Response(200, json={'sent': False})

    service = mock_sender(client, handler)
    for attempt in range(1, 4):
        assert client.portal.call(service.deliver_next)
        row = rows(client)[0]
        assert row['attempts'] == attempt
        assert row['status'] == ('FAILED' if attempt == 3 else 'PENDING')
        assert not client.portal.call(service.deliver_next)  # Backoff is enforced.
        with connect(client.app.state.database_path) as connection:
            connection.execute('UPDATE telegram_notifications SET next_attempt = 0')
    assert not client.portal.call(service.deliver_next)
    assert len(requests) == 3
    assert client.get(f'/trades/{trade.trade_id}').json() == before


def test_real_simulated_entry_enqueues_once(client):
    enabled(client)
    create_active_level(client, json=dict(instrument='NIFTY', price=25000, enabled=True))
    for price in [24900, 25000, 25000]:
        assert client.post('/simulation/tick', json={'instrument': 'NIFTY', 'price': price}).status_code == 200
    trades = client.get('/trades').json()
    assert len(trades) == len(rows(client)) == 1
    assert rows(client)[0]['trade_id'] == trades[0]['trade_id']
    assert 'Index level touched: 25,000.00' in rows(client)[0]['message']


def test_background_worker_delivers_without_delaying_entry(tmp_path, monkeypatch):
    sent = []
    requests = []
    initialize = TelegramNotifications.__init__

    async def handler(request):
        requests.append(request)
        sent[0].set()
        return httpx.Response(200, json={'sent': True})

    def mocked_initialize(self, path):
        initialize(self, path, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(TelegramNotifications, '__init__', mocked_initialize)
    monkeypatch.setattr(TelegramNotifications, 'run', RUN_WORKER)
    with TestClient(create_app(tmp_path / 'background.sqlite3')) as client:
        async def create_event():
            return asyncio.Event()
        sent.append(client.portal.call(create_event))
        enabled(client)
        trade = add_trade(client)
        assert client.get(f'/trades/{trade.trade_id}').status_code == 200
        client.portal.call(asyncio.wait_for, sent[0].wait(), 3)
        assert len(requests) == 1
    # Lifespan waits for cancellation and closes the sender on exit.
    assert client.app.state.telegram_notifications.client.is_closed
