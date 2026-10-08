"""Minute observations and immutable chart audit snapshots; no strategy decisions."""
import json
import math
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.database import connect

IST = ZoneInfo('Asia/Kolkata')


def parse_timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def initialize_charts(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS chart_candles (
        symbol TEXT NOT NULL, source TEXT NOT NULL, time INTEGER NOT NULL,
        open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
        volume REAL, origin TEXT NOT NULL, PRIMARY KEY(symbol, source, time))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS chart_fetches (
        symbol TEXT, source TEXT, date TEXT, fetched_at TEXT NOT NULL,
        PRIMARY KEY(symbol, source, date))''')
    connection.execute('''CREATE TABLE IF NOT EXISTS chart_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, instrument TEXT NOT NULL,
        event_type TEXT NOT NULL, timestamp TEXT NOT NULL, data TEXT NOT NULL)''')
    connection.execute('CREATE INDEX IF NOT EXISTS chart_events_lookup ON chart_events(instrument, timestamp)')


def record_chart_event(connection, instrument, event_type, timestamp, **data):
    connection.execute('INSERT INTO chart_events(instrument,event_type,timestamp,data) VALUES (?,?,?,?)',
                       (instrument, event_type, timestamp.isoformat(), json.dumps(data)))


def record_arm(connection, row, price, timestamp):
    if row['enabled'] and row['status'] == 'ACTIVE':
        record_chart_event(connection, row['instrument'], 'LEVEL_ARMED', timestamp,
                           level_id=row['id'], level=row['price'], price=price,
                           direction='FROM_ABOVE' if price >= row['price'] else 'FROM_BELOW')


def session_bounds(day):
    return (datetime.combine(day, time(9, 15), IST), datetime.combine(day, time(15, 30), IST))


class CandleRepository:
    def __init__(self, path, source):
        self.path, self.source = path, source

    def observe(self, symbol, price, timestamp):
        local = timestamp.astimezone(IST)
        if not math.isfinite(price) or price < 0 or not time(9, 15) <= local.time() < time(15, 30):
            return None
        minute = int(timestamp.timestamp()) // 60 * 60
        with connect(self.path) as c:
            c.execute('''INSERT INTO chart_candles VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,source,time) DO UPDATE SET
                high=MAX(high,excluded.high),low=MIN(low,excluded.low),close=excluded.close''',
                (symbol, self.source, minute, price, price, price, price, None, 'RECEIVED_TICKS'))
            return dict(c.execute('SELECT * FROM chart_candles WHERE symbol=? AND source=? AND time=?',
                                 (symbol, self.source, minute)).fetchone())

    def list(self, symbol, day):
        start, end = session_bounds(day)
        with connect(self.path) as c:
            return [dict(row) for row in c.execute('''SELECT * FROM chart_candles
                WHERE symbol=? AND source=? AND time>=? AND time<? ORDER BY time''',
                (symbol, self.source, int(start.timestamp()), int(end.timestamp())))]

    def fetched_at(self, symbol, day):
        with connect(self.path) as c:
            row = c.execute('SELECT fetched_at FROM chart_fetches WHERE symbol=? AND source=? AND date=?',
                            (symbol, self.source, day.isoformat())).fetchone()
            return datetime.fromisoformat(row[0]) if row else None

    def cache(self, symbol, day, rows, now):
        start, end = session_bounds(day)
        candles = []
        for row in rows:
            stamp = parse_timestamp(row[0])
            if stamp.tzinfo is None:
                raise ValueError('Historical candle timestamp lacks timezone')
            values = [float(v) for v in row[1:6]]
            o, h, l, close, volume = values
            if not all(math.isfinite(v) for v in values) or l < 0 or not l <= min(o, close) <= max(o, close) <= h or volume < 0:
                raise ValueError('Invalid historical candle')
            if start <= stamp < end and stamp <= now:
                candles.append((symbol, self.source, int(stamp.timestamp()) // 60 * 60,
                                o, h, l, close, volume, 'ZERODHA_HISTORY'))
        with connect(self.path) as c:
            c.executemany('''INSERT INTO chart_candles VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,source,time) DO UPDATE SET open=excluded.open,high=excluded.high,
                low=excluded.low,close=excluded.close,volume=excluded.volume,origin=excluded.origin
                WHERE chart_candles.time < ?''', [(*row, int(now.timestamp()) // 60 * 60) for row in candles])
            c.execute('INSERT OR REPLACE INTO chart_fetches VALUES (?,?,?,?)',
                      (symbol, self.source, day.isoformat(), now.astimezone(timezone.utc).isoformat()))
