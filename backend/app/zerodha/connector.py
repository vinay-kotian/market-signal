import csv
import hashlib
import io
import os
from typing import Literal
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from app.zerodha.auth_errors import LoginError
from pydantic import BaseModel, SecretStr, field_validator


class MarketSettings(BaseModel):
    market_data_mode: Literal['SIMULATED', 'ZERODHA'] = 'SIMULATED'
    api_key: SecretStr = SecretStr('')
    api_secret: SecretStr = SecretStr('')
    access_token: SecretStr = SecretStr('')
    redirect_url: str = 'http://127.0.0.1:8000/zerodha/callback'
    frontend_url: str = 'http://127.0.0.1:5173'

    @field_validator('redirect_url', 'frontend_url')
    @classmethod
    def validate_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Configure an absolute HTTP(S) URL without credentials, query or fragment')
        return value.rstrip('/')

    def backend_login_url(self):
        parsed = urlsplit(self.redirect_url)
        return urlunsplit((parsed.scheme, parsed.netloc, '/zerodha/login', '', ''))

    @classmethod
    def from_environment(cls):
        return cls(market_data_mode=os.getenv('MARKET_DATA_MODE', 'SIMULATED'),
                   api_key=os.getenv('ZERODHA_API_KEY', ''),
                   api_secret=os.getenv('ZERODHA_API_SECRET', ''),
                   access_token=os.getenv('ZERODHA_ACCESS_TOKEN', ''),
                   redirect_url=os.getenv('ZERODHA_REDIRECT_URL', 'http://127.0.0.1:8000/zerodha/callback'),
                   frontend_url=os.getenv('FRONTEND_URL', 'http://127.0.0.1:5173'))


class KiteConnector:
    """Deliberately exposes only login, instrument-master and quote operations."""
    def __init__(self, settings, client=None, session_store=None):
        self.settings = settings
        self.session_store = session_store
        self._token = settings.access_token
        if not self._token.get_secret_value() and session_store:
            self._token = SecretStr(session_store.load() or '')
        self.client = client or httpx.AsyncClient(base_url='https://api.kite.trade', timeout=15)

    @property
    def authenticated(self):
        return bool(self._token.get_secret_value())

    def login_url(self, state=None):
        if not self.settings.api_key.get_secret_value():
            raise LoginError('API_KEY_MISSING', 'Set ZERODHA_API_KEY in the backend terminal and restart the backend.')
        if not self.settings.api_secret.get_secret_value():
            raise LoginError('API_SECRET_MISSING', 'Set ZERODHA_API_SECRET from the same Kite app in the backend terminal and restart the backend.')
        params = dict(v=3, api_key=self.settings.api_key.get_secret_value())
        if state is not None:
            params['redirect_params'] = urlencode({'state': state})
        return 'https://kite.zerodha.com/connect/login?' + urlencode(params)

    async def exchange(self, request_token):
        key, secret = self.settings.api_key.get_secret_value(), self.settings.api_secret.get_secret_value()
        if not key or not secret:
            raise LoginError('CREDENTIALS_MISSING', 'Set both ZERODHA_API_KEY and ZERODHA_API_SECRET in the backend terminal, then restart.')
        if key != key.strip() or secret != secret.strip():
            raise LoginError('CREDENTIAL_WHITESPACE', 'The configured API key or secret contains surrounding whitespace. Re-copy both values from the same Kite app and restart the backend.')
        checksum = hashlib.sha256((key + request_token + secret).encode()).hexdigest()
        try:
            response = await self.client.post('/session/token', data=dict(
                api_key=key, request_token=request_token, checksum=checksum), headers={'X-Kite-Version': '3'})
        except httpx.RequestError as error:
            raise LoginError('TOKEN_EXCHANGE_NETWORK_ERROR', 'The backend could not reach Kite for token exchange. Check network and TLS certificate configuration, then retry.') from error
        if response.status_code != 200:
            # Classify known errors without exposing arbitrary broker response text.
            try:
                message = response.json().get('message', '')
                message = message.lower() if isinstance(message, str) else ''
            except (ValueError, AttributeError):
                message = ''
            if 'checksum' in message:
                raise LoginError('INVALID_CHECKSUM', 'Kite reports an invalid checksum. Re-copy the current API key and API secret from the same Kite developer app, fully restart the backend, and start a new login. If that still fails, contact Kite support with this error code.')
            if 'request_token' in message or 'token is invalid or has expired' in message:
                raise LoginError('REQUEST_TOKEN_REJECTED', 'Kite rejected the request token as invalid, expired, or already used. Close old login tabs and start once from Connect Zerodha; do not refresh the callback URL.')
            if 'api_key' in message:
                raise LoginError('API_KEY_REJECTED', 'Kite rejected the API key. Check the current key in your Kite developer app, fully restart the backend, and begin a fresh login.')
            raise LoginError('TOKEN_EXCHANGE_REJECTED', f'Kite rejected token exchange (HTTP {response.status_code}). Verify that the API key and secret belong to the same Kite app, restart the backend, and begin a fresh login.')
        try:
            token = response.json().get('data', {}).get('access_token')
        except (ValueError, AttributeError) as error:
            raise LoginError('TOKEN_RESPONSE_INVALID', 'Kite returned an unexpected token response. Retry login.') from error
        if not isinstance(token, str) or not token:
            raise LoginError('TOKEN_RESPONSE_INVALID', 'Kite did not return an access token. Retry login.')
        if self.session_store:
            try:
                self.session_store.save(token)
            except OSError as error:
                raise LoginError('SESSION_SAVE_FAILED', 'The backend could not save the session. Check write permissions on the backend database directory.') from error
        self._token = SecretStr(token)  # Never returned to the browser.

    async def _get(self, path, **kwargs):
        if not self.authenticated:
            raise ValueError('Zerodha login required')
        response = await self.client.get(path, headers={'X-Kite-Version': '3', 'Authorization':
            f'token {self.settings.api_key.get_secret_value()}:{self._token.get_secret_value()}'}, **kwargs)
        if response.status_code in (401, 403):
            self.expire()
            raise ValueError('Zerodha session expired; login again')
        if response.status_code != 200:
            raise ValueError('Zerodha market-data request failed')
        return response

    async def instruments(self):
        response = await self._get('/instruments')
        return list(csv.DictReader(io.StringIO(response.text)))

    async def ltp(self, exchange, symbol):
        key = f'{exchange}:{symbol}'
        response = await self._get('/quote/ltp', params={'i': key})
        return response.json().get('data', {}).get(key, {}).get('last_price')

    def expire(self):
        self._token = SecretStr('')
        if self.session_store:
            self.session_store.clear()

    def websocket_url(self):
        return 'wss://ws.kite.trade?' + urlencode(dict(
            api_key=self.settings.api_key.get_secret_value(), access_token=self._token.get_secret_value()))

    async def close(self):
        await self.client.aclose()
