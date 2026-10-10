from fastapi import HTTPException
from app.indices import SUPPORTED_INDICES


class SimulationFlow:
    def __init__(self, levels, positions, prices, instruments, market_close=None, atr_data=None):
        self.levels, self.positions, self.prices = levels, positions, prices
        self.market_close = market_close
        self.atr_data = atr_data
        self.instruments = instruments
        self.refresh_instruments()

    def refresh_instruments(self):
        self.option_symbols = {c.symbol for symbol in SUPPORTED_INDICES
                               for c in self.instruments.contracts(symbol)}

    async def on_tick(self, tick):
        if self.atr_data:
            self.atr_data.observe(tick.instrument, tick.price, self.levels._clock())
        if tick.instrument in self.option_symbols or self.positions.trades.has_symbol(tick.instrument):
            if tick.price < 0:
                raise HTTPException(status_code=422, detail='Option price must be nonnegative')
            await self.positions.on_tick(tick)
            self.prices.set_price(tick.instrument, tick.price)
        else:
            await self.levels.on_tick(tick)
        if self.market_close:
            await self.market_close.check()
