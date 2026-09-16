import pytest
from fastapi.testclient import TestClient

from app.database import DEFAULT_DATABASE_PATH
from app.main import create_app
from app.settings import TradeSettings
from test_zerodha_login import application


def test_database_path_environment_preserves_development_default(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_PATH', raising=False)
    assert create_app().state.database_path == DEFAULT_DATABASE_PATH
    destination = tmp_path / 'stockpi.db'
    monkeypatch.setenv('DATABASE_PATH', str(destination))
    app = create_app()
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
    assert destination.exists()
    assert create_app(tmp_path / 'explicit.db').state.database_path == tmp_path / 'explicit.db'


def test_execution_mode_environment(monkeypatch):
    monkeypatch.delenv('TRADE_MODE', raising=False)
    monkeypatch.setenv('EXECUTION_MODE', 'PAPER')
    assert TradeSettings.from_environment().trade_mode == 'PAPER'
    monkeypatch.setenv('TRADE_MODE', 'LIVE')
    with pytest.raises(ValueError, match='conflicts'):
        TradeSettings.from_environment()
    monkeypatch.setenv('EXECUTION_MODE', 'LIVE')
    with pytest.raises(ValueError, match='must be PAPER'):
        TradeSettings.from_environment()


def test_production_login_preserves_api_prefix_and_cookie(tmp_path):
    app, store, _ = application(tmp_path)
    with TestClient(app, base_url='https://stockpi.vkotian.com', root_path='/api') as client:
        config = app.state.market_settings
        config.redirect_url = 'https://stockpi.vkotian.com/api/zerodha/callback'
        config.frontend_url = 'https://stockpi.vkotian.com'
        assert config.backend_login_url() == 'https://stockpi.vkotian.com/api/zerodha/login'
        # Simulate the external paths with ASGI root_path, as Uvicorn does behind Nginx.
        response = client.get('/api/zerodha/login', follow_redirects=False)
        assert response.status_code == 303
        assert 'Path=/api/zerodha' in response.headers['set-cookie']
        assert 'Secure' in response.headers['set-cookie']
        from urllib.parse import parse_qs, urlsplit
        params = parse_qs(urlsplit(response.headers['location']).query)
        nonce = parse_qs(params['redirect_params'][0])['state'][0]
        response = client.get('/api/zerodha/callback', params={'state': nonce, 'request_token': 'mock'}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == 'https://stockpi.vkotian.com/connection'
        assert client.get('/api/connection').json()['auth_status'] == 'CONNECTED'
        assert store.load() == 'private-access-token'
