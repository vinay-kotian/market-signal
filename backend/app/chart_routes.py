"""Read-only instrument details, scoped to PAPER records and the configured feed."""
import json
from datetime import date as Date, time
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.chart_data import IST, session_bounds, parse_timestamp
from app.database import connect
from app.date_range import timestamp_scope
from app.indices import SUPPORTED_INDICES
from app.trade_models import Trade
from app.trading_date import trading_date

router = APIRouter(prefix='/instruments', tags=['instrument charts'])


def identity(state, value):
    service = state.zerodha_instruments
    record = None
    if service:
        record = (service.by_token(int(value)) if value.isdigit() else
                  service.index(value) or service.option(value))
    if record:
        return dict(symbol=record.underlying if record.instrument_type == 'INDEX' else record.trading_symbol,
                    instrument=record.underlying, instrument_type=record.instrument_type,
                    instrument_token=record.instrument_token, strike=record.strike,
                    expiry=record.expiry.isoformat() if record.expiry else None)
    if value in SUPPORTED_INDICES:
        return dict(symbol=value, instrument=value, instrument_type='INDEX', instrument_token=None)
    # Retain identity for expired, delisted and simulated traded contracts. Tokens are
    # deliberately not inferred from today's master (exchange tokens may be reused).
    with connect(state.database_path) as c:
        row = c.execute("SELECT * FROM trades WHERE option_symbol=? AND trade_mode='PAPER' ORDER BY trade_id DESC LIMIT 1", (value,)).fetchone()
    if row:
        return dict(symbol=value, instrument=row['instrument'], instrument_type=row['option_type'],
                    instrument_token=None, strike=row['strike'], expiry=row['expiry'])
    raise HTTPException(404, 'Unknown instrument or PAPER option contract')


def associated_trades(state, item, day):
    column = 'instrument' if item['instrument_type'] == 'INDEX' else 'option_symbol'
    with connect(state.database_path) as c:
        _, (start, end) = timestamp_scope(c, 'entry_time', day, day)
        return [Trade(**dict(row)).model_dump(mode='json') for row in c.execute(f'''
            SELECT * FROM trades WHERE trade_mode='PAPER' AND {column}=?
            AND utc_timestamp(entry_time) < ?
            AND (exit_time IS NULL OR utc_timestamp(exit_time) >= ?) ORDER BY trade_id''',
            (item['symbol'], end, start))]


@router.get('/{instrument}/trades')
async def trades(instrument: str, request: Request, date: Date):
    item = identity(request.app.state, instrument)
    return dict(instrument=item, date=date, mode='PAPER', trades=associated_trades(request.app.state, item, date))


@router.get('/{instrument}/candles')
async def candles(instrument: str, request: Request, date: Date, interval: Literal['minute'] = 'minute'):
    state = request.app.state
    item = identity(state, instrument)
    now = state.level_repository.clock()
    if date > trading_date(now):
        raise HTTPException(422, 'Future trading dates are unavailable')
    repository = state.chart_candles
    symbol = item['symbol']
    message = None
    if state.market_settings.market_data_mode == 'ZERODHA':
        # One lazy request per instrument/day; concurrent browser requests share a lock.
        async with state.chart_fetch_lock:
            fetched = repository.fetched_at(symbol, date)
            complete = date < trading_date(now) or now.astimezone(IST).time() >= time(15, 30)
            cache_fresh = fetched and ((complete and fetched.astimezone(IST).date() > date)
                or (complete and fetched.astimezone(IST).time() >= time(15, 30))
                or (now - fetched).total_seconds() < 60)
            expired = item.get('expiry') and Date.fromisoformat(item['expiry']) < trading_date(now)
            if not cache_fresh:
                if expired or not item.get('instrument_token'):
                    message = 'Only saved candles are available for this contract; a safe historical token is unavailable.'
                elif not state.kite.authenticated:
                    message = 'Zerodha login required to retrieve missing historical candles; saved candles are shown.'
                elif now < session_bounds(date)[0]:
                    message = 'The trading session has not started; saved candles are shown.'
                else:
                    start, end = session_bounds(date)
                    try:
                        rows = await state.kite.historical_candles(item['instrument_token'], start, min(end, now.astimezone(IST)))
                        repository.cache(symbol, date, rows, now)
                    except (ValueError, TypeError, KeyError, IndexError, httpx.HTTPError):
                        message = 'Historical candles are unavailable from Zerodha; saved candles are shown. Retry after checking the connection.'
    rows = repository.list(symbol, date)
    if not rows and not message:
        message = 'No candles available for this date. Only received ticks or broker history are plotted.'
    elif state.market_settings.market_data_mode == 'SIMULATED':
        message = 'Candles contain received simulated ticks only; gaps and unobserved OHLC extremes are not filled.'
    elif any(row['origin'] == 'RECEIVED_TICKS' for row in rows) and not message:
        message = 'Some candles contain received ticks only and may omit movement before the feed connected.'
    return dict(instrument=item, date=date, interval=interval, timezone='Asia/Kolkata',
                source=repository.source, candles=rows, message=message, as_of=now.isoformat())


@router.get('/{instrument}/events')
async def events(instrument: str, request: Request, date: Date):
    state = request.app.state
    item = identity(state, instrument)
    result = []
    with connect(state.database_path) as c:
        _, (start, end) = timestamp_scope(c, 'timestamp', date, date)
        # BACKTEST normally lives in a separate DB. Also defend against imported rows.
        signals = [dict(row) for row in c.execute('''SELECT s.* FROM signals s
            WHERE instrument=? AND utc_timestamp(timestamp) >= ? AND utc_timestamp(timestamp) < ?
            AND NOT EXISTS (SELECT 1 FROM trades t WHERE t.signal_id=s.id AND t.trade_mode='BACKTEST')
            ORDER BY julianday(timestamp),id''', (item['instrument'], start, end))]
        signal_ids = {s['id'] for s in signals}
        if item['instrument_type'] == 'INDEX':
            for row in c.execute('''SELECT * FROM chart_events WHERE instrument=?
                AND utc_timestamp(timestamp) >= ? AND utc_timestamp(timestamp) < ? ORDER BY id''',
                (item['instrument'], start, end)):
                data = json.loads(row['data'])
                if data.get('signal_id') is not None and data['signal_id'] not in signal_ids:
                    continue
                result.append(dict(id=f"audit-{row['id']}", event_type=row['event_type'], timestamp=row['timestamp'], **data))
            for signal in signals:
                result.append(dict(id=f"signal-{signal['id']}", event_type='SIGNAL_GENERATED' if signal['valid'] else 'SIGNAL_REJECTED',
                    timestamp=signal['timestamp'], price=signal['trigger_price'], level=signal['level'],
                    level_id=signal['level_id'], direction=signal['direction'], signal_id=signal['id'],
                    rejection_reason=signal['rejection_reason']))
        for trade in associated_trades(state, item, date):
            signal = c.execute('SELECT * FROM signals WHERE id=?', (trade['signal_id'],)).fetchone()
            metadata = dict(trade_id=trade['trade_id'], signal_id=trade['signal_id'],
                level=trade['trigger_level'], direction=trade['direction'], option_symbol=trade['option_symbol'],
                strike=trade['strike'], expiry=trade['expiry'], option_type=trade['option_type'], quantity=trade['quantity'],
                index_price=signal['trigger_price'] if signal else None, entry_time=trade['entry_time'])
            if item['instrument_type'] == 'INDEX':
                if signal and trading_date(parse_timestamp(signal['timestamp'])) == date:
                    result.append(dict(id=f"trigger-trade-{trade['trade_id']}", event_type='TRADE_TRIGGERED',
                                       timestamp=signal['timestamp'], price=signal['trigger_price'], **metadata))
                continue
            # Entry and exit are persisted executions, even for older trades whose
            # event rows were migrated. Protection history is never reconstructed.
            if trading_date(parse_timestamp(trade['entry_time'])) == date:
                result.append(dict(id=f"entry-{trade['trade_id']}", event_type='TRADE_ENTRY',
                    timestamp=trade['entry_time'], price=trade['entry_price'], initial_stop_loss=trade['initial_stop_loss'], **metadata))
            if trade['exit_time'] and trading_date(parse_timestamp(trade['exit_time'])) == date:
                duration = (parse_timestamp(trade['exit_time']) - parse_timestamp(trade['entry_time'])).total_seconds()
                result.append(dict(id=f"exit-{trade['trade_id']}", event_type='TRADE_EXIT', timestamp=trade['exit_time'],
                    price=trade['exit_price'], exit_reason=trade['exit_reason'], realised_pnl=trade['realised_pnl'],
                    realised_pnl_percentage=trade['realised_pnl_percentage'], duration_seconds=duration, **metadata))
            for row in c.execute('''SELECT * FROM trade_events WHERE trade_id=? AND reconstructed=0
                AND event_type NOT IN ('POSITION_OPENED','POSITION_CLOSED')
                AND utc_timestamp(timestamp) >= ? AND utc_timestamp(timestamp) < ? ORDER BY id''',
                (trade['trade_id'], start, end)):
                result.append({**dict(row), 'id': f"protection-{row['id']}", **metadata})
    result.sort(key=lambda event: (parse_timestamp(event['timestamp']), event['id']))
    return dict(instrument=item, date=date, mode='PAPER', events=result,
                message='Initial arming and touch/cross detail is recorded from this version onward. Older persisted signals and executions remain available.')
