"""Strategy 3: deterministic long-only one-minute SMA ATR, fixed SL and target.

Candle timestamps denote the START of the minute. This module has no broker,
repository, signal or clock dependencies.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal
from math import isfinite
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.decision_context import DecisionRejection

IST = ZoneInfo('Asia/Kolkata')
MINUTE = timedelta(minutes=1)


def dec(value):
    return Decimal(str(value))


class FixedAtrSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    atr_period: int = Field(default=14, ge=1, le=200, strict=True)
    atr_multiplier: float = Field(default=.75, gt=0, allow_inf_nan=False)
    atr_method: Literal['SMA'] = 'SMA'
    min_pre_entry_candles: int = Field(default=2, ge=2, strict=True)
    fallback_sl_pct: float = Field(default=20, gt=0, lt=100, allow_inf_nan=False)
    risk_reward_ratio: float = Field(default=2, gt=0, allow_inf_nan=False)
    eod_exit_time: time = time(15, 25)
    max_initial_risk_pct: Optional[float] = Field(default=None, gt=0, lt=100, allow_inf_nan=False)
    slippage_model: Literal['none'] = 'none'
    entry_candle_policy: Literal['SKIP_PARTIAL_ENTRY_CANDLE', 'FULL_CANDLE_APPROXIMATION'] = 'SKIP_PARTIAL_ENTRY_CANDLE'

    @field_validator('eod_exit_time')
    @classmethod
    def whole_minute(cls, value):
        if value.tzinfo or value.second or value.microsecond:
            raise ValueError('EOD cutoff must be a local whole minute')
        return value


class OptionMinuteCandle(BaseModel):
    symbol: str = Field(min_length=1)
    timestamp: AwareDatetime
    open: float = Field(gt=0, allow_inf_nan=False)
    high: float = Field(gt=0, allow_inf_nan=False)
    low: float = Field(ge=0, allow_inf_nan=False)
    close: float = Field(ge=0, allow_inf_nan=False)
    volume: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid(self):
        if self.timestamp.second or self.timestamp.microsecond:
            raise ValueError('Minute candles must start on a minute boundary')
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError('Invalid minute OHLC')
        self.timestamp = self.timestamp.astimezone(IST)
        return self

    @property
    def completed_at(self):
        return self.timestamp + MINUTE


def local(timestamp):
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError('Timestamp must be timezone-aware')
    return timestamp.astimezone(IST)


def prepare_candles(candles, symbol):
    rows, warnings, seen = [], [], set()
    for raw in candles:
        candle = raw if isinstance(raw, OptionMinuteCandle) else OptionMinuteCandle.model_validate(
            raw.model_dump() if isinstance(raw, BaseModel) else raw)
        if candle.symbol != symbol:
            raise ValueError('OPTION_CONTRACT_MISMATCH')
        if candle.timestamp in seen:
            raise ValueError('DUPLICATE_MINUTE_CANDLE')
        seen.add(candle.timestamp)
        rows.append(candle)
    rows.sort(key=lambda c: c.timestamp)
    for previous, current in zip(rows, rows[1:]):
        if current.timestamp - previous.timestamp != MINUTE:
            warnings.append(f'MISSING_MINUTE_CANDLES:{previous.completed_at.isoformat()}:{current.timestamp.isoformat()}')
    return rows, warnings


def entry_plan(entry_price, entry_time, symbol, candles, settings=None):
    settings = settings or FixedAtrSettings()
    entry_time = local(entry_time)
    entry = dec(entry_price)
    if not entry.is_finite() or entry <= 0:
        raise ValueError('INVALID_ENTRY_PRICE')
    cutoff = datetime.combine(entry_time.date(), settings.eod_exit_time, IST)
    if entry_time >= cutoff:
        raise ValueError('STRATEGY3_EOD_CUTOFF_REACHED')
    # Filter before quality/ATR preparation so future observations cannot affect entry.
    def start(candle):
        value = candle.timestamp if isinstance(candle, BaseModel) else candle['timestamp']
        return local(datetime.fromisoformat(value) if isinstance(value, str) else value)

    eligible = [c for c in candles if start(c) + MINUTE <= entry_time]
    rows, warnings = prepare_candles(eligible, symbol)
    trs = []
    for previous, current in zip(rows, rows[1:]):
        # A gap has no immediately preceding candle. Do not invent its close.
        if current.timestamp - previous.timestamp == MINUTE:
            high, low, close = dec(current.high), dec(current.low), dec(previous.close)
            trs.append(max(high-low, abs(high-close), abs(low-close)))
    samples = trs[-settings.atr_period:]
    atr = sum(samples, Decimal(0)) / len(samples) if samples and len(rows) >= settings.min_pre_entry_candles else None
    reason = None
    if len(rows) < settings.min_pre_entry_candles:
        reason = 'INSUFFICIENT_PRE_ENTRY_CANDLES'
    elif atr is None or not atr.is_finite() or atr <= 0:
        reason = 'ATR_UNAVAILABLE_OR_INVALID'
    stop = entry - atr * dec(settings.atr_multiplier) if reason is None else None
    if stop is not None and (not stop.is_finite() or not 0 < stop < entry):
        reason = 'ATR_STOP_INVALID'
    if reason:
        stop = entry * (1-dec(settings.fallback_sl_pct)/100)
    if not stop.is_finite() or not 0 < stop < entry:
        raise ValueError('FALLBACK_STOP_INVALID')
    risk = entry-stop
    risk_pct = risk/entry*100
    if settings.max_initial_risk_pct is not None and risk_pct > dec(settings.max_initial_risk_pct):
        raise DecisionRejection('MAX_INITIAL_RISK_EXCEEDED', dict(initial_stop=float(stop),
            initial_risk_percent=float(risk_pct), option_atr=float(atr) if atr is not None else None,
            attempted_stop_source='FALLBACK' if reason else 'ATR', fallback_reason=reason))
    target = entry+risk*dec(settings.risk_reward_ratio)
    if not target.is_finite() or not isfinite(float(target)):
        raise ValueError('TARGET_INVALID')
    return dict(pre_entry_candle_count=len(rows), valid_tr_count=len(trs), atr_value=float(atr) if atr is not None else None, atr_sample_count=len(samples),
        atr_multiplier=settings.atr_multiplier, stop_source='FALLBACK' if reason else 'ATR',
        initial_stop=float(stop), stop_distance=float(risk), initial_risk_pct=float(risk_pct),
        target=float(target), risk_reward_ratio=settings.risk_reward_ratio, fallback_reason=reason,
        data_quality_warnings=warnings, applied_entry_candle_policy=settings.entry_candle_policy,
        frozen_strategy_settings=settings.model_dump(mode='json'))


def candle_exit(candle, entry_time, plan):
    settings = FixedAtrSettings(**plan['frozen_strategy_settings'])
    entry_time = local(entry_time)
    if candle.completed_at <= entry_time:
        return None
    if candle.timestamp < entry_time and settings.entry_candle_policy == 'SKIP_PARTIAL_ENTRY_CANDLE':
        return None
    cutoff = datetime.combine(entry_time.date(), settings.eod_exit_time, IST)
    if candle.completed_at > cutoff:
        return None
    if candle.low <= plan['initial_stop']:
        return 'SL', plan['initial_stop']
    if candle.high >= plan['target']:
        return 'TARGET', plan['target']
    return None


def simulate_trade(*, trade_id, instrument, option_symbol, entry_time, entry_price, quantity,
                   candles, settings=None, brokerage=0, taxes=0, slippage_cost=0, other_fees=0):
    """Standalone trade-record/Excel replay. No invented outcomes on missing data."""
    base = dict(trade_id=trade_id, instrument=instrument, option_contract=option_symbol,
                entry_timestamp=entry_time.isoformat(), entry_price=entry_price, quantity=quantity)
    try:
        base['entry_timestamp'] = local(entry_time).isoformat()
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError('INVALID_QUANTITY')
        costs = [dec(v) for v in (brokerage, taxes, slippage_cost, other_fees)]
        if any(not c.is_finite() or c < 0 for c in costs):
            raise ValueError('INVALID_COSTS')
        rows, warnings = prepare_candles(candles, option_symbol)
        plan = entry_plan(entry_price, entry_time, option_symbol, rows, settings)
        base.update(plan)
        base['data_quality_warnings'] = warnings
        cutoff = datetime.combine(local(entry_time).date(), time.fromisoformat(plan['frozen_strategy_settings']['eod_exit_time']), IST)
        eligible = [c for c in rows if c.completed_at > local(entry_time) and c.completed_at <= cutoff]
        # Missing post-entry minutes make chronological first-touch claims unknowable.
        expected = local(entry_time).replace(second=0, microsecond=0)
        if local(entry_time) != expected and plan['applied_entry_candle_policy'] == 'SKIP_PARTIAL_ENTRY_CANDLE':
            expected += MINUTE
        last = None
        for candle in eligible:
            if candle.timestamp < expected:
                continue
            if candle.timestamp != expected:
                return {**base, 'status': 'DATA_INCOMPLETE', 'reason': 'MISSING_POST_ENTRY_MINUTE'}
            last = candle
            hit = candle_exit(candle, entry_time, plan)
            if hit:
                reason, price = hit
                break
            expected += MINUTE
        else:
            if last is None or last.completed_at != cutoff:
                return {**base, 'status': 'DATA_INCOMPLETE', 'reason': 'MISSING_EOD_CANDLE'}
            reason, price = 'EOD', last.close
        gross = (dec(price)-dec(entry_price))*quantity
        return {**base, 'status': 'CLOSED', 'exit_timestamp': last.completed_at.isoformat(),
            'exit_price': price, 'exit_reason': reason, 'gross_pnl': float(gross),
            'net_pnl': float(gross-sum(costs)), 'return_percentage': float((dec(price)/dec(entry_price)-1)*100),
            'realized_r_multiple': float((dec(price)-dec(entry_price))/dec(plan['stop_distance'])),
            'holding_duration_seconds': (last.completed_at-local(entry_time)).total_seconds()}
    except ValueError as error:
        return {**base, 'status': 'REJECTED', 'reason': str(error)}
