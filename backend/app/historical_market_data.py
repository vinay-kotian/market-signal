"""Recorded ticks and dated contract catalogues; never synthesize historical prices."""
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Literal, Protocol, Optional
from datetime import date

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.market_data import PriceTick
from app.option_instruments import OptionContract
from app.atr_data import AtrCandle


class HistoricalTick(PriceTick):
    timestamp: AwareDatetime
    price: float = Field(ge=0, allow_inf_nan=False)


class HistoricalContract(BaseModel):
    instrument: Literal['NIFTY', 'BANKNIFTY', 'SENSEX']
    expiry: date
    strike: int = Field(gt=0)
    option_type: Literal['CE', 'PE']
    symbol: str = Field(min_length=1)
    lot_size: int = Field(gt=0, strict=True)
    instrument_token: Optional[int] = Field(default=None, gt=0)


class HistoricalDataset(BaseModel):
    contracts: list[HistoricalContract] = Field(min_length=1, max_length=10000)
    ticks: list[HistoricalTick] = Field(min_length=1, max_length=100000)
    source: str = Field(default='USER_SUPPLIED', max_length=200)
    candles: list[AtrCandle] = Field(default_factory=list, max_length=100000)

    @model_validator(mode='after')
    def unique_contracts(self):
        symbols = [c.symbol for c in self.contracts]
        identities = [(c.instrument, c.expiry, c.strike, c.option_type) for c in self.contracts]
        if len(set(symbols)) != len(symbols) or len(set(identities)) != len(identities):
            raise ValueError('Historical contract symbols and identities must be unique')
        if any(symbol in ('NIFTY', 'BANKNIFTY', 'SENSEX') for symbol in symbols):
            raise ValueError('Option symbols must differ from underlying symbols')
        keys = [(c.symbol, c.timestamp) for c in self.candles]
        if len(set(keys)) != len(keys):
            raise ValueError('Historical ATR candle identities must be unique')
        return self


class HistoricalDataSource(Protocol):
    def load(self, trading_date: date, instrument: str) -> HistoricalDataset: ...


class LocalHistoricalDataSource:
    """Adapter for exported historical data, replaceable by an external archive."""
    def __init__(self, directory):
        self.directory = Path(directory)

    def load(self, trading_date, instrument):
        path = self.directory / f'{trading_date.isoformat()}-{instrument}.json'
        if not path.is_file():
            raise ValueError('Historical data unavailable. Upload a dated contract catalogue and '
                             'recorded spot/option ticks, or install a JSON archive file in HISTORICAL_DATA_DIRECTORY.')
        return HistoricalDataset.model_validate_json(path.read_text())


class HistoricalOptionInstrumentSource:
    def __init__(self, contracts):
        self._contracts = [OptionContract(c.instrument, c.expiry, c.strike,
                                          c.option_type, c.symbol, c.lot_size) for c in contracts]

    def strike_step(self, instrument):
        return {'NIFTY': 50, 'BANKNIFTY': 100, 'SENSEX': 100}.get(instrument)

    def contracts(self, instrument):
        return [c for c in self._contracts if c.instrument == instrument]


class HistoricalMarketDataProvider:
    def __init__(self, consumer):
        self._consumer = consumer

    async def publish(self, tick: PriceTick):
        await self._consumer(tick)

    async def replay(self, records, advance_clock):
        # Stable ordering: simultaneous records preserve archive order.
        for record in sorted(records, key=lambda item: item.timestamp):
            await advance_clock(record.timestamp)
            await self.publish(PriceTick(instrument=record.instrument, price=record.price))
            await asyncio.sleep(0)
