from datetime import date, datetime, timezone
from functools import reduce
from math import gcd
from typing import Optional

from pydantic import BaseModel, Field

from app.database import connect
from app.option_instruments import OptionContract


class Instrument(BaseModel):
    instrument_token: int = Field(gt=0)
    exchange_token: Optional[int] = None
    trading_symbol: str = Field(min_length=1)
    name: str
    underlying: str
    exchange: str
    segment: str
    instrument_type: str
    strike: float = Field(ge=0, allow_inf_nan=False)
    expiry: Optional[date] = None
    lot_size: int = Field(ge=0)
    tick_size: float = Field(ge=0, allow_inf_nan=False)


def normalize(row):
    symbol = row.get('tradingsymbol', '')
    indices = {'NIFTY 50': 'NIFTY', 'NIFTY BANK': 'BANKNIFTY'}
    is_index = row.get('exchange') == 'NSE' and row.get('segment') == 'INDICES' and symbol in indices
    is_option = (row.get('exchange') == 'NFO' and row.get('segment') == 'NFO-OPT'
                 and row.get('instrument_type') in ('CE', 'PE') and row.get('name') in ('NIFTY', 'BANKNIFTY'))
    if not (is_index or is_option):
        return None
    result = Instrument(instrument_token=row['instrument_token'], exchange_token=row.get('exchange_token') or None,
        trading_symbol=symbol, name=row.get('name', ''), underlying=indices[symbol] if is_index else row['name'],
        exchange=row['exchange'], segment=row['segment'], instrument_type='INDEX' if is_index else row['instrument_type'],
        strike=row.get('strike') or 0, expiry=row.get('expiry') or None,
        lot_size=row.get('lot_size') or 0, tick_size=row.get('tick_size') or 0)
    if is_option and (not result.expiry or result.lot_size <= 0 or not result.strike.is_integer()):
        raise ValueError('Invalid option metadata')
    return result


class ZerodhaInstrumentService:
    def __init__(self, path, connector):
        self.path, self.connector = path, connector
        self.status = 'NOT_SYNCED'
        self.last_sync = None
        with connect(path) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS zerodha_instruments (exchange TEXT, symbol TEXT, data TEXT, PRIMARY KEY(exchange, symbol))')
            connection.execute('CREATE TABLE IF NOT EXISTS zerodha_sync (id INTEGER PRIMARY KEY CHECK(id=1), timestamp TEXT)')
            rows = connection.execute('SELECT data FROM zerodha_instruments').fetchall()
            last = connection.execute('SELECT timestamp FROM zerodha_sync WHERE id=1').fetchone()
        self.install([Instrument.model_validate_json(row['data']) for row in rows])
        if last:
            self.last_sync, self.status = last['timestamp'], 'SYNCED'

    async def sync(self):
        self.status = 'SYNCING'
        try:
            records = [item for row in await self.connector.instruments() if (item := normalize(row)) is not None]
            if {r.underlying for r in records if r.instrument_type == 'INDEX'} != {'NIFTY', 'BANKNIFTY'}:
                raise ValueError('Instrument master is missing required indices')
            if len({r.instrument_token for r in records}) != len(records):
                raise ValueError('Duplicate instrument tokens')
            timestamp = datetime.now(timezone.utc).isoformat()
            with connect(self.path) as connection:
                connection.execute('DELETE FROM zerodha_instruments')
                connection.executemany('INSERT INTO zerodha_instruments VALUES (?, ?, ?)',
                    [(r.exchange, r.trading_symbol, r.model_dump_json()) for r in records])
                connection.execute('INSERT OR REPLACE INTO zerodha_sync VALUES (1, ?)', (timestamp,))
            self.install(records)
            self.last_sync, self.status = timestamp, 'SYNCED'
        except Exception:
            self.status = 'FAILED'
            raise

    def install(self, records):
        self.records = records
        self._tokens = {r.instrument_token: r for r in records}
        self._indices = {r.underlying: r for r in records if r.instrument_type == 'INDEX'}
        self._options = {r.trading_symbol: r for r in records if r.instrument_type in ('CE', 'PE')}

    def index(self, underlying):
        return self._indices.get(underlying)

    def option(self, symbol):
        return self._options.get(symbol)

    def by_token(self, token):
        return self._tokens.get(token)

    def contracts(self, instrument):
        return [OptionContract(r.underlying, r.expiry, int(r.strike), r.instrument_type, r.trading_symbol, r.lot_size)
                for r in self.records if r.underlying == instrument and r.instrument_type in ('CE', 'PE')]

    def strike_step(self, instrument):
        strikes = sorted({c.strike for c in self.contracts(instrument)})
        gaps = [b - a for a, b in zip(strikes, strikes[1:])]
        return reduce(gcd, gaps) if gaps else None
