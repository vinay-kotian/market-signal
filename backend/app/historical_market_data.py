"""Historical input uses the same normalized tick contract as simulation."""
import asyncio

from pydantic import AwareDatetime, Field

from app.market_data import PriceTick


class HistoricalTick(PriceTick):
    timestamp: AwareDatetime
    price: float = Field(ge=0, allow_inf_nan=False)


class HistoricalMarketDataProvider:
    def __init__(self, consumer):
        self._consumer = consumer

    async def publish(self, tick: PriceTick):
        await self._consumer(tick)

    async def replay(self, records, advance_clock):
        # Python's stable sort preserves source order for simultaneous observations.
        for record in sorted(records, key=lambda item: item.timestamp):
            await advance_clock(record.timestamp)
            await self.publish(PriceTick(instrument=record.instrument, price=record.price))
            await asyncio.sleep(0)  # Cooperate with the app event loop without wall-clock delays.
