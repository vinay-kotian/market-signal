"""Read-only, dated Kite archives for the existing BACKTEST engine."""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from app.atr_data import AtrCandle
from app.database import connect
from app.historical_market_data import (HistoricalContract, HistoricalDataset,
    HistoricalOptionInstrumentSource, HistoricalTick, MinuteCandle)
from app.option_selector import OptionSelector
from app.trading_time import TradingTimeRules
from app.zerodha.instruments import Instrument

IST = TradingTimeRules.timezone
ASSUMPTIONS = [
    'Index signals use completed minute closes; intraminute index touches are not inferred.',
    'Entries use the next option candle open after a signal, never the completed candle close.',
    'Completed option candles test low, then high, then low again, then close through shared protection. '
    'This is a conservative stress assumption, not a reconstructed tick path; triggered exits fill at the low.',
    'Mandatory exits use the first option open at or after the deadline. Stops in the preceding '
    'completed candle are evaluated first. Exact intraminute exit times are unknown.',
    'Costs use the existing flat per-order estimate. No separate slippage model is configured; '
    'adverse candle-low fills are the execution assumption.',
]


def aggregate_five_minutes(candles):
    groups = {}
    for candle in candles:
        start = int(candle.timestamp.timestamp()) // 300 * 300
        groups.setdefault((candle.symbol, start), []).append(candle)
    result = []
    for (symbol, start), group in sorted(groups.items()):
        group.sort(key=lambda c: c.timestamp)
        if [int(c.timestamp.timestamp()) for c in group] != list(range(start, start+300, 60)):
            continue  # Never invent a missing minute for ATR.
        result.append(AtrCandle(symbol=symbol, timestamp=datetime.fromtimestamp(start, IST),
            open=group[0].open, high=max(c.high for c in group), low=min(c.low for c in group), close=group[-1].close))
    return result


class ZerodhaHistoricalDataLoader:
    def __init__(self, directory, instruments, connector, clock):
        self.directory = Path(directory)
        self.instruments, self.connector, self.clock = instruments, connector, clock
        self._lock = None

    def catalogue(self, day):
        with connect(self.instruments.path) as connection:
            row = connection.execute('SELECT trading_date, observed_at, records FROM zerodha_instrument_catalogues '
                                     'WHERE trading_date=?', (str(day),)).fetchone()
            if row is None:
                # The previous implementation saved only the latest dump. Reuse
                # it only if it was observed on the actual historical date.
                observed = self.instruments.last_sync
                if observed:
                    observed_day = datetime.fromisoformat(observed).astimezone(IST).date()
                    if observed_day == day:
                        return self.instruments.records, observed, []
                raise ValueError(f'Historical option catalogue unavailable for {day}. Current instruments cannot '
                                 'prove that day\'s nearest expiry. Supply a dated archive or use a date with a saved Zerodha catalogue.')
        return [Instrument.model_validate(r) for r in json.loads(row['records'])], row['observed_at'], []

    def cache_key(self, record, start, end, interval):
        identity = [record.model_dump(mode='json'), start.isoformat(), end.isoformat(), interval]
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    async def fetch(self, record, start, end, interval):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / 'zerodha-history.sqlite3'
        key = self.cache_key(record, start, end, interval)
        with connect(path) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS history_cache (key TEXT PRIMARY KEY, rows TEXT NOT NULL)')
            saved = connection.execute('SELECT rows FROM history_cache WHERE key=?', (key,)).fetchone()
        if saved:
            return json.loads(saved['rows']), True
        if record.expiry and record.expiry < self.clock().astimezone(IST).date():
            raise ValueError(f'Historical option token unavailable safely for expired contract {record.trading_symbol}; '
                             'use previously cached data or a supplied archive')
        if not self.connector.authenticated:
            raise ValueError('Zerodha login required to download historical data; reconnect in Connection settings')
        try:
            rows = await self.connector.historical_candles(record.instrument_token, start, end, interval=interval)
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(f'Zerodha historical request failed for {record.trading_symbol}; check connection and retry') from error
        # Validation and completeness happen before the caller saves anything.
        return rows, False

    def save(self, record, start, end, interval, rows):
        with connect(self.directory / 'zerodha-history.sqlite3') as connection:
            connection.execute('INSERT OR REPLACE INTO history_cache VALUES (?, ?)',
                               (self.cache_key(record, start, end, interval), json.dumps(rows, default=str)))

    async def minutes(self, record, symbol, start, end):
        rows, cached = await self.fetch(record, start, end, 'minute')
        candles = []
        try:
            for row in rows:
                candle = MinuteCandle(symbol=symbol, timestamp=row[0], open=row[1], high=row[2], low=row[3], close=row[4], volume=row[5])
                if start <= candle.timestamp < end:
                    candles.append(candle)
        except (ValueError, TypeError, IndexError) as error:
            raise ValueError(f'Invalid historical candles for {symbol}') from error
        candles.sort(key=lambda c: c.timestamp)
        expected = list(range(int(start.timestamp()), int(end.timestamp()), 60))
        actual = [int(c.timestamp.timestamp()) for c in candles]
        if actual != expected:
            raise ValueError(f'Historical candle coverage incomplete for {symbol}: expected {len(expected)} minute candles, '
                             f'received {len(actual)}. Missing/duplicate minutes are not filled; the date may be a holiday.')
        if symbol in ('NIFTY', 'BANKNIFTY') and any(c.low <= 0 or c.close <= 0 for c in candles):
            raise ValueError('Historical index prices must be positive')
        if not cached:
            self.save(record, start, end, 'minute', rows)
        return candles, cached

    async def warmup(self, record, symbol, start):
        begin = start-timedelta(days=10)
        rows, cached = await self.fetch(record, begin, start, '5minute')
        try:
            candles = [AtrCandle(symbol=symbol, timestamp=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in rows]
        except (ValueError, TypeError, IndexError) as error:
            raise ValueError(f'Invalid ATR warmup candles for {symbol}') from error
        candles = sorted((c for c in candles if begin <= c.timestamp and c.timestamp+timedelta(minutes=5) <= start),
                         key=lambda c: c.timestamp)
        if len({c.timestamp for c in candles}) != len(candles):
            raise ValueError(f'Duplicate ATR warmup candles for {symbol}')
        if not cached:
            self.save(record, begin, start, '5minute', rows)
        return candles

    async def load(self, config):
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            return await self._load(config)

    async def _load(self, config):
        day = config.trading_date
        start = datetime.combine(day, config.market_open_time, IST)
        end = datetime.combine(day, config.market_close_time, IST)
        now = self.clock().astimezone(IST)
        if day.weekday() >= 5:
            raise ValueError('Selected date is a weekend; choose a completed trading session')
        if end > now:
            raise ValueError('Zerodha historical backtests require a completed trading session')
        if self.instruments is None or self.connector is None:
            raise ValueError('Configure Zerodha market data and connect Zerodha before using historical backtests')
        records, observed, warnings = self.catalogue(day)
        observed_at = datetime.fromisoformat(observed).astimezone(IST)
        if observed_at.date() != day or observed_at > end:
            raise ValueError(f'Historical catalogue for {day} was observed after the session; '
                             'expiring contracts may already have been removed. Supply a reliable dated archive.')
        index = next((r for r in records if r.underlying == config.instrument and r.instrument_type == 'INDEX'), None)
        if not index:
            raise ValueError(f'Historical index token unavailable for {config.instrument}')
        contracts = [HistoricalContract(instrument=r.underlying, expiry=r.expiry, strike=int(r.strike),
            option_type=r.instrument_type, symbol=r.trading_symbol, lot_size=r.lot_size, instrument_token=r.instrument_token)
            for r in records if r.underlying == config.instrument and r.instrument_type in ('CE', 'PE') and r.expiry >= day]
        if not contracts:
            raise ValueError(f'Historical option contracts unavailable for {config.instrument} on {day}')
        index_candles, cached = await self.minutes(index, config.instrument, start, end)
        coverage = {config.instrument: dict(expected_minutes=len(index_candles), received_minutes=len(index_candles), complete=True, cached=cached)}
        source = HistoricalOptionInstrumentSource(contracts)
        selector = OptionSelector(source)
        # Prefetch only the contracts the shared selector could select at recorded
        # closes. This freezes one common dataset for LEGACY/ATR comparisons.
        candidates = set()
        for candle in index_candles:
            for direction in ('FROM_ABOVE', 'FROM_BELOW'):
                selected = selector.select(config.instrument, candle.close, direction, config.itm_depth, day)
                if selected.status == 'SELECTED':
                    candidates.add(selected.option_symbol)
        minute_candles = list(index_candles)
        atr_candles = aggregate_five_minutes(index_candles)
        errors = {}
        lookup = {r.trading_symbol: r for r in records}
        for symbol in sorted(candidates):
            try:
                candles, cached = await self.minutes(lookup[symbol], symbol, start, end)
                minute_candles.extend(candles)
                atr_candles.extend(aggregate_five_minutes(candles))
                coverage[symbol] = dict(expected_minutes=len(index_candles), received_minutes=len(candles), complete=True, cached=cached)
            except ValueError as error:
                errors[symbol] = str(error)
                coverage[symbol] = dict(expected_minutes=len(index_candles), complete=False, error=str(error))
                warnings.append(f'{symbol}: candidate data unavailable. A run selecting this contract will fail: {error}')
                continue
            # Fetch warmup for both strategies so comparisons use identical data.
            # Unavailable ATR warmup is a visible warning, not fabricated ATR.
            try:
                atr_candles.extend(await self.warmup(lookup[symbol], symbol, start))
            except ValueError as error:
                warnings.append(f'{symbol}: ATR warmup unavailable: {error}; entries require sufficient completed option candles.')
        ticks = []
        for candle in minute_candles:
            if candle.symbol == config.instrument:
                ticks.append(HistoricalTick(instrument=candle.symbol, timestamp=candle.completed_at,
                                            price=candle.close, observation='INDEX_CLOSE'))
            else:
                ticks.append(HistoricalTick(instrument=candle.symbol, timestamp=candle.timestamp,
                                            price=candle.open, observation='OPTION_OPEN'))
                ticks.append(HistoricalTick(instrument=candle.symbol, timestamp=candle.completed_at,
                                            price=candle.close, observation='OPTION_CANDLE'))
        priority = {'OPTION_CANDLE': 0, 'INDEX_CLOSE': 1, 'OPTION_OPEN': 2}
        ticks.sort(key=lambda t: (t.timestamp, priority[t.observation], t.instrument))
        return HistoricalDataset(source='ZERODHA_HISTORICAL', contracts=contracts, ticks=ticks, candles=atr_candles,
            minute_candles=minute_candles, data_resolution='1_MINUTE_OHLC', execution_model='CANDLE_APPROXIMATION',
            coverage=dict(catalogue_observed_at=observed, symbols=coverage, assumptions=ASSUMPTIONS),
            warnings=warnings, option_data_errors=errors)
