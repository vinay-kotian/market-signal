"""Completed option/index candles and Wilder ATR, independent of broker/strategy."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import isfinite
from typing import Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.database import connect
from app.trading_time import TradingTimeRules


class AtrCandle(BaseModel):
    model_config = ConfigDict(extra='forbid')
    symbol: str = Field(min_length=1, max_length=200)
    timestamp: AwareDatetime
    available_at: Optional[AwareDatetime] = None
    open: float = Field(gt=0, allow_inf_nan=False)
    high: float = Field(gt=0, allow_inf_nan=False)
    low: float = Field(ge=0, allow_inf_nan=False)
    close: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid_candle(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError('Invalid OHLC prices')
        if self.timestamp.second or self.timestamp.microsecond or int(self.timestamp.timestamp()) % 300:
            raise ValueError('ATR candles must start on a five-minute boundary')
        if self.available_at and self.available_at < self.timestamp + timedelta(minutes=5):
            raise ValueError('A candle cannot be available before it completes')
        return self


def initialize_atr(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS atr_candles (
        symbol TEXT NOT NULL, source TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
        open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
        available_at REAL NOT NULL, origin TEXT NOT NULL, PRIMARY KEY(symbol, source, start))''')


def wilder_atr(rows, period):
    previous = value = None
    seed = Decimal(0)
    count = 0
    for row in rows:
        high, low, close = (Decimal(str(row[key])) for key in ('high', 'low', 'close'))
        tr = high - low if previous is None else max(high-low, abs(high-previous), abs(low-previous))
        previous = close
        count += 1
        if count <= period:
            seed += tr
            if count == period:
                value = seed / period
        else:
            value = (value * (period-1) + tr) / period
    return float(value) if value is not None else None


class AtrData:
    def __init__(self, path, source):
        self.path, self.source = path, source

    def observe(self, symbol, price, timestamp):
        if not isfinite(price) or price < 0:
            return
        start = int(timestamp.timestamp()) // 300 * 300
        with connect(self.path) as connection:
            connection.execute('''INSERT INTO atr_candles VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,source,start) DO UPDATE SET high=MAX(high,excluded.high),
                low=MIN(low,excluded.low),close=excluded.close,available_at=excluded.available_at
                WHERE atr_candles.origin='RECORDED_TICKS' ''',
                (symbol, self.source, start, start+300, price, price, price, price,
                 timestamp.timestamp(), 'RECORDED_TICKS'))

    def cache(self, candles, origin='HISTORICAL_OHLC'):
        with connect(self.path) as connection:
            for candle in candles:
                start = int(candle.timestamp.timestamp())
                available = (candle.available_at or candle.timestamp+timedelta(minutes=5)).timestamp()
                connection.execute('''INSERT INTO atr_candles VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol,source,start) DO UPDATE SET open=excluded.open,high=excluded.high,
                    low=excluded.low,close=excluded.close,available_at=excluded.available_at,origin=excluded.origin''',
                    (candle.symbol, self.source, start, start+300, candle.open, candle.high,
                     candle.low, candle.close, available, origin))

    def value(self, symbol, timestamp, period, connection=None):
        if connection is None:
            with connect(self.path) as connection:
                return self.value(symbol, timestamp, period, connection)
        cutoff = timestamp.timestamp()
        # Both conditions matter for delayed historical observations and replay.
        where = 'symbol=? AND source=? AND end<=? AND available_at<=?'
        params = (symbol, self.source, cutoff, cutoff)
        rows = connection.execute(f'SELECT high,low,close FROM atr_candles WHERE {where} ORDER BY start', params)
        value = wilder_atr(rows, period)
        last = connection.execute(f'SELECT end,origin FROM atr_candles WHERE {where} ORDER BY start DESC LIMIT 1', params).fetchone()
        return dict(value=value, candle_end=datetime.fromtimestamp(last['end'], timezone.utc) if last else None,
                    source=self.source, origin=last['origin'] if last else None)


class ZerodhaAtrData(AtrData):
    def __init__(self, path, instruments, connector, clock):
        super().__init__(path, 'ZERODHA')
        self.instruments, self.connector, self.clock = instruments, connector, clock
        self.prepared = {}

    async def prepare(self, symbol, instrument):
        # Kite query strings use exchange-local time, without an offset.
        now = self.clock().astimezone(TradingTimeRules.timezone)
        completed = int(now.timestamp()) // 300
        for name, record in ((symbol, self.instruments.option(symbol)), (instrument, self.instruments.index(instrument))):
            if record is None or self.prepared.get(name) == completed:
                continue
            try:
                rows = await self.connector.historical_candles(record.instrument_token, now-timedelta(days=10), now,
                                                               interval='5minute')
                candles = []
                for row in rows:
                    candle = AtrCandle(symbol=name, timestamp=row[0], open=row[1], high=row[2], low=row[3], close=row[4])
                    if candle.timestamp+timedelta(minutes=5) <= now:
                        candles.append(candle)
                self.cache(candles, 'ZERODHA_HISTORY')
                self.prepared[name] = completed
            except Exception:
                import logging
                logging.getLogger(__name__).warning('ATR historical candles unavailable for %s', name)
