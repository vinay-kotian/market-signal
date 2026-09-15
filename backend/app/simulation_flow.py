from fastapi import HTTPException


class SimulationFlow:
    def __init__(self, levels, positions, prices, instruments, market_close=None):
        self.levels, self.positions, self.prices = levels, positions, prices
        self.market_close = market_close
        self.option_symbols = {c.symbol for symbol in ['NIFTY', 'BANKNIFTY']
                               for c in instruments.contracts(symbol)}

    async def on_tick(self, tick):
        if tick.instrument in self.option_symbols or self.positions.trades.has_symbol(tick.instrument):
            if tick.price < 0:
                raise HTTPException(status_code=422, detail='Option price must be nonnegative')
            await self.positions.on_tick(tick)
            self.prices.set_price(tick.instrument, tick.price)
        else:
            await self.levels.on_tick(tick)
        if self.market_close:
            await self.market_close.check()
