import asyncio
import secrets
import logging
from app.zerodha.auth_errors import LoginError, describe
import time
from urllib.parse import urlsplit
from fastapi.responses import RedirectResponse
from app.zerodha.auth_logging import redact_callback_logs

redact_callback_logs()
from contextlib import suppress

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, SecretStr

router = APIRouter(tags=['market connection'])


def require_zerodha(request):
    if request.app.state.market_settings.market_data_mode != 'ZERODHA':
        raise HTTPException(status_code=409, detail='Enable ZERODHA mode in the backend environment first')
    return request.app.state


@router.get('/connection')
def connection_status(request: Request):
    return connection_snapshot(request.app.state)


def connection_snapshot(state):
    provider = state.market_data_provider
    instruments = state.zerodha_instruments
    auth_status = ('NOT_CONNECTED' if state.kite is None else
                   'ERROR' if state.zerodha_auth_error else
                   'CONNECTED' if state.kite.authenticated else
                   'AUTH_REQUIRED' if state.market_settings.api_key.get_secret_value() else 'NOT_CONNECTED')
    configuration_error = None
    if state.kite is not None:
        if not state.market_settings.api_key.get_secret_value():
            configuration_error = describe(LoginError('API_KEY_MISSING', 'Set ZERODHA_API_KEY in the backend terminal and restart.'))
        elif not state.market_settings.api_secret.get_secret_value():
            configuration_error = describe(LoginError('API_SECRET_MISSING', 'Set ZERODHA_API_SECRET from the same Kite app in the backend terminal and restart.'))
    available_instruments = ([symbol for symbol in ('NIFTY', 'BANKNIFTY')
                              if instruments.index(symbol) is not None] if instruments else ['NIFTY', 'BANKNIFTY'])
    return dict(available_instruments=available_instruments, auth_error=state.zerodha_auth_error_detail or configuration_error, auth_status=auth_status, login_url=state.market_settings.backend_login_url(), market_data_mode=state.market_settings.market_data_mode, execution_mode='PAPER',
                connection_status=getattr(provider, 'status', 'SIMULATED'),
                authenticated=bool(state.kite and state.kite.authenticated),
                instrument_sync_status=instruments.status if instruments else 'NOT_APPLICABLE',
                last_successful_sync=instruments.last_sync if instruments else None,
                prices=dict(state.live_prices), price_changes=dict(state.live_price_changes),
                subscribed_instrument_count=len(getattr(provider, 'subscribed', set())),
                ticks_received=getattr(provider, 'ticks_received', 0),
                last_tick_at=getattr(provider, 'last_tick_at', None),
                reconnect_count=getattr(provider, 'reconnect_count', 0))


@router.get('/zerodha/login-url')
def login_url(request: Request):
    try:
        return {'url': require_zerodha(request).market_settings.backend_login_url()}
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


class TokenInput(BaseModel):
    request_token: SecretStr


async def restart(state):
    if state.zerodha_task:
        state.zerodha_task.cancel()
        with suppress(asyncio.CancelledError):
            await state.zerodha_task
    state.zerodha_task = asyncio.create_task(state.market_data_provider.run())


@router.post('/zerodha/session')
async def create_session(body: TokenInput, request: Request):
    state = require_zerodha(request)
    async with state.connection_lock:
        try:
            await state.kite.exchange(body.request_token.get_secret_value())
        except Exception:
            raise HTTPException(status_code=400, detail='Login exchange failed; check configuration and obtain a fresh request token')
        state.zerodha_auth_error = False
        await restart(state)
    state.live_publisher.connection()
    return {'status': 'AUTHENTICATED'}


@router.post('/zerodha/instruments/sync')
async def sync_instruments(request: Request):
    state = require_zerodha(request)
    async with state.connection_lock:
        try:
            await state.zerodha_instruments.sync()
            state.simulation_flow.refresh_instruments()
        except Exception:
            state.live_publisher.connection()
            raise HTTPException(status_code=502, detail='Instrument sync failed; check session and retry')
        await restart(state)
    state.live_publisher.connection()
    return {'status': 'SYNCED', 'last_successful_sync': state.zerodha_instruments.last_sync}


@router.get('/zerodha/login')
async def login(request: Request):
    state = require_zerodha(request)
    try:
        state.kite.login_url()  # Validate the API key before starting a login.
    except ValueError as error:
        state.zerodha_auth_error = True
        state.zerodha_auth_error_detail = describe(error)
        raise HTTPException(status_code=409, detail=str(error)) from error
    # Start on the callback's host so the HttpOnly cookie also works when the
    # frontend is opened using localhost while the callback uses 127.0.0.1.
    if request.url.hostname != urlsplit(state.market_settings.redirect_url).hostname:
        return RedirectResponse(state.market_settings.backend_login_url(), status_code=303)
    nonce = secrets.token_urlsafe(32)
    state.zerodha_login_state = (nonce, time.monotonic() + 600)
    state.zerodha_auth_error = False
    state.zerodha_auth_error_detail = None
    response = RedirectResponse(state.kite.login_url(nonce), status_code=303)
    response.set_cookie('zerodha_login_state', nonce, httponly=True, samesite='lax',
                        secure=urlsplit(state.market_settings.redirect_url).scheme == 'https',
                        max_age=600, path=state.market_settings.login_cookie_path())
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@router.get('/zerodha/callback')
async def callback(request: Request):
    state = require_zerodha(request)
    async with state.connection_lock:
        pending = state.zerodha_login_state
        state.zerodha_login_state = None  # Consume the attempt once, including failures.
        valid = (pending is not None and pending[1] >= time.monotonic()
                 and secrets.compare_digest(pending[0], request.query_params.get('state', ''))
                 and secrets.compare_digest(pending[0], request.cookies.get('zerodha_login_state', '')))
        token = request.query_params.get('request_token', '')
        try:
            if pending is None:
                raise LoginError('LOGIN_ATTEMPT_MISSING', 'The login attempt was lost or already used. Avoid restarting the backend during login, and click Connect Zerodha again.')
            if pending[1] < time.monotonic():
                raise LoginError('LOGIN_EXPIRED', 'The login attempt expired. Click Connect Zerodha and complete login within ten minutes.')
            if not request.query_params.get('state'):
                raise LoginError('LOGIN_STATE_MISSING', 'Kite returned without the login state. Check the registered callback URL and begin a fresh login from Connect Zerodha.')
            if not request.cookies.get('zerodha_login_state'):
                raise LoginError('LOGIN_COOKIE_MISSING', 'The login cookie did not reach the callback. Register the exact ZERODHA_REDIRECT_URL in Kite, including 127.0.0.1 versus localhost, and use the same browser for login.')
            if not valid:
                raise LoginError('LOGIN_STATE_MISMATCH', 'This callback belongs to a different login attempt. Close older login tabs and start once from Connect Zerodha.')
            if request.query_params.get('status', 'success') != 'success':
                raise LoginError('LOGIN_DECLINED', 'Kite login was cancelled or declined. Click Connect Zerodha to retry.')
            if not token:
                raise LoginError('REQUEST_TOKEN_MISSING', 'Kite returned without a request token. Complete a fresh login from Connect Zerodha.')
            await state.kite.exchange(token)
            state.zerodha_auth_error = False
            state.zerodha_auth_error_detail = None
            await restart(state)
        except Exception as error:
            state.zerodha_auth_error = True
            state.zerodha_auth_error_detail = describe(error)
            logging.getLogger(__name__).warning('Zerodha login failed: %s', state.zerodha_auth_error_detail['code'])
        state.live_publisher.connection()
        response = RedirectResponse(state.market_settings.frontend_url + '/connection', status_code=303)
        response.delete_cookie('zerodha_login_state', path=state.market_settings.login_cookie_path())
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response
