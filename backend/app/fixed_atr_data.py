"""Source-isolated minute history adapter for Strategy 3."""
from datetime import datetime, timedelta, timezone
from app.database import connect
from app.fixed_atr import OptionMinuteCandle, prepare_candles


class FixedAtrData:
    def __init__(self, path, source):
        self.path, self.source = path, source + '_STRATEGY3'

    def cache(self, candles):
        # Reject duplicates rather than letting an UPSERT pick an arbitrary version.
        grouped = {}
        for candle in candles:
            grouped.setdefault(candle.symbol, []).append(candle)
        validated = [c for symbol, rows in grouped.items() for c in prepare_candles(rows, symbol)[0]]
        with connect(self.path) as connection:
            for c in validated:
                start = int(c.timestamp.timestamp())
                connection.execute('''INSERT OR REPLACE INTO atr_candles VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (c.symbol, self.source, start, start+60, c.open, c.high, c.low, c.close, start+60, 'HISTORICAL_OHLC'))

    def observe(self, symbol, price, timestamp):
        start = int(timestamp.timestamp()) // 60 * 60
        with connect(self.path) as connection:
            connection.execute('''INSERT INTO atr_candles VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,source,start) DO UPDATE SET high=MAX(high,excluded.high),
                low=MIN(low,excluded.low),close=excluded.close,available_at=excluded.available_at
                WHERE atr_candles.origin='RECORDED_TICKS' ''',
                (symbol, self.source, start, start+60, price, price, price, price,
                 timestamp.timestamp(), 'RECORDED_TICKS'))

    def candles(self, symbol, timestamp, connection):
        rows = connection.execute('''SELECT * FROM atr_candles WHERE symbol=? AND source=?
            AND end<=? AND available_at<=? ORDER BY start''',
            (symbol, self.source, timestamp.timestamp(), timestamp.timestamp())).fetchall()
        return [OptionMinuteCandle(symbol=symbol, timestamp=datetime.fromtimestamp(r['start'], timezone.utc),
            open=r['open'], high=r['high'], low=r['low'], close=r['close']) for r in rows]

    async def prepare(self, atr_data, symbol):
        if not hasattr(atr_data, 'connector'):
            return
        record = atr_data.instruments.option(symbol)
        if record is None:
            return
        now = atr_data.clock()
        try:
            rows = await atr_data.connector.historical_candles(record.instrument_token,
                now-timedelta(days=1), now, interval='minute')
            candles = [OptionMinuteCandle(symbol=symbol, timestamp=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in rows]
            self.cache([c for c in candles if c.completed_at <= now])
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Strategy 3 minute history unavailable for %s; entry will evaluate fallback', symbol)
