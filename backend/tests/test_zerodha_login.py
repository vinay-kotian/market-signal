import json
import logging
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.zerodha.auth_logging import CallbackTokenFilter
from app.zerodha.connector import KiteConnector, MarketSettings
from app.zerodha.session_store import SessionStore


def application(tmp_path, key='test-key', fail=False):
    settings = MarketSettings(market_data_mode='ZERODHA', api_key=key, api_secret='private-secret')
    store = SessionStore(tmp_path/'data.zerodha-session.json', key)
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == '/session/token':
            return httpx.Response(400 if fail else 200, json={'data': {'access_token': 'private-access-token'}})
        # Any startup instrument call after reload remains mocked.
        return httpx.Response(200, text='instrument_token,tradingsymbol\n')
    connector = KiteConnector(settings, httpx.AsyncClient(base_url='https://mock.invalid',
                               transport=httpx.MockTransport(respond)), store)
    def forbidden_socket(*args, **kwargs):
        raise AssertionError('No real socket allowed in authentication tests')
    app = create_app(tmp_path/'data.sqlite3', market_settings=settings,
                     kite_connector=connector, socket_factory=forbidden_socket)
    return app, store, requests


def begin(client):
    response = client.get('/zerodha/login', follow_redirects=False)
    assert response.status_code == 303
    parsed = urlsplit(response.headers['location'])
    assert parsed.hostname == 'kite.zerodha.com'
    query = parse_qs(parsed.query)
    assert query['api_key'] == ['test-key']
    assert 'private-secret' not in response.text + response.headers['location']
    assert 'HttpOnly' in response.headers['set-cookie']
    return parse_qs(query['redirect_params'][0])['state'][0]


def test_missing_api_key(tmp_path):
    app, _, requests = application(tmp_path, key='')
    with TestClient(app, base_url='http://127.0.0.1:8000') as client:
        response = client.get('/zerodha/login', follow_redirects=False)
        assert response.status_code == 409
        assert 'ZERODHA_API_KEY' in response.json()['detail']
        assert requests == []


def test_callback_success_and_persistent_session(tmp_path):
    app, store, requests = application(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1:8000') as client:
        assert client.get('/connection').json()['auth_status'] == 'AUTH_REQUIRED'
        state = begin(client)
        response = client.get('/zerodha/callback', params={'state': state, 'request_token': 'one-time-token', 'status': 'success'}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == 'http://127.0.0.1:5173/connection'
        assert response.headers['referrer-policy'] == 'no-referrer'
        status = client.get('/connection')
        assert status.json()['auth_status'] == 'CONNECTED'
        assert status.json()['execution_mode'] == 'PAPER'
        assert 'private-access-token' not in status.text + response.text + str(response.headers)
        assert store.load() == 'private-access-token'
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert '/session/token' == requests[0].url.path
        # Consumed callback cannot exchange a second time.
        client.get('/zerodha/callback', params={'state': state, 'request_token': 'one-time-token'}, follow_redirects=False)
        assert len([r for r in requests if r.url.path == '/session/token']) == 1
    reloaded, _, _ = application(tmp_path)
    with TestClient(reloaded, base_url='http://127.0.0.1:8000') as client:
        assert client.get('/connection').json()['auth_status'] == 'CONNECTED'
        reloaded.state.kite.expire()
        assert not store.path.exists()
        assert client.get('/connection').json()['auth_status'] == 'AUTH_REQUIRED'


@pytest.mark.parametrize('failure', ['exchange', 'missing_token', 'bad_state', 'no_cookie', 'expired', 'declined'])
def test_callback_failures(tmp_path, failure):
    app, store, requests = application(tmp_path, fail=failure == 'exchange')
    with TestClient(app, base_url='http://127.0.0.1:8000') as client:
        state = begin(client)
        params = {'request_token': 'one-time-token', 'state': state}
        if failure == 'missing_token': params.pop('request_token')
        if failure == 'bad_state': params['state'] = 'wrong'
        if failure == 'no_cookie': client.cookies.clear()
        if failure == 'expired': app.state.zerodha_login_state = (state, time.monotonic() - 1)
        if failure == 'declined': params['status'] = 'error'
        response = client.get('/zerodha/callback', params=params, follow_redirects=False)
        assert response.headers['location'].endswith('/connection')
        status = client.get('/connection').json()
        assert status['auth_status'] == 'ERROR'
        expected = {'exchange': 'TOKEN_EXCHANGE_REJECTED', 'missing_token': 'REQUEST_TOKEN_MISSING',
                    'bad_state': 'LOGIN_STATE_MISMATCH', 'no_cookie': 'LOGIN_COOKIE_MISSING',
                    'expired': 'LOGIN_EXPIRED', 'declined': 'LOGIN_DECLINED'}
        assert status['auth_error']['code'] == expected[failure]
        assert 'one-time-token' not in json.dumps(status)
        assert not store.path.exists()
        if failure != 'exchange': assert requests == []


def test_configured_redirect_host_and_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('ZERODHA_REDIRECT_URL', 'http://127.0.0.1:8100/zerodha/callback')
    monkeypatch.setenv('FRONTEND_URL', 'http://127.0.0.1:5174')
    settings = MarketSettings.from_environment()
    assert settings.backend_login_url() == 'http://127.0.0.1:8100/zerodha/login'
    assert settings.frontend_url == 'http://127.0.0.1:5174'
    app, _, _ = application(tmp_path)
    with TestClient(app, base_url='http://localhost:8000') as client:
        response = client.get('/zerodha/login', follow_redirects=False)
        assert response.headers['location'] == 'http://127.0.0.1:8000/zerodha/login'


def test_store_expiry_and_api_key_binding(tmp_path):
    store = SessionStore(tmp_path/'session', 'key')
    store.save('secret')
    assert SessionStore(store.path, 'different-key').load() is None
    data = json.loads(store.path.read_text())
    data['expires_at'] = '2000-01-01T00:00:00+00:00'
    store.path.write_text(json.dumps(data))
    assert store.load() is None
    assert not store.path.exists()


def test_callback_query_is_redacted_from_access_log():
    record = logging.LogRecord('uvicorn.access', 20, '', 0, '%s - "%s %s HTTP/%s" %s',
        ('127.0.0.1', 'GET', '/zerodha/callback?request_token=secret&state=nonce', '1.1', 303), None)
    CallbackTokenFilter().filter(record)
    assert 'secret' not in record.getMessage()
    assert '/zerodha/callback HTTP' in record.getMessage()


def test_missing_secret_is_reported_before_login(tmp_path):
    app, _, requests = application(tmp_path)
    from pydantic import SecretStr
    with TestClient(app, base_url='http://127.0.0.1:8000') as client:
        app.state.market_settings.api_secret = SecretStr('')
        status = client.get('/connection').json()
        assert status['auth_error']['code'] == 'API_SECRET_MISSING'
        response = client.get('/zerodha/login', follow_redirects=False)
        assert response.status_code == 409
        assert 'ZERODHA_API_SECRET' in response.json()['detail']
        assert requests == []


@pytest.mark.parametrize('message,code', [
    ('Invalid `checksum`.', 'INVALID_CHECKSUM'),
    ('Invalid `request_token`.', 'REQUEST_TOKEN_REJECTED'),
    ('Token is invalid or has expired.', 'REQUEST_TOKEN_REJECTED'),
    ('Invalid `api_key`.', 'API_KEY_REJECTED'),
    ('unexpected response containing private-token', 'TOKEN_EXCHANGE_REJECTED'),
])
def test_broker_rejection_diagnostics_are_sanitized(message, code):
    import asyncio
    from app.zerodha.auth_errors import LoginError
    async def check():
        client = httpx.AsyncClient(base_url='https://mock.invalid', transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={'message': message})))
        connector = KiteConnector(MarketSettings(api_key='key', api_secret='secret'), client)
        try:
            with pytest.raises(LoginError) as caught:
                await connector.exchange('request-token')
            assert caught.value.code == code
            assert 'private-token' not in str(caught.value)
        finally:
            await connector.close()
    asyncio.run(check())
