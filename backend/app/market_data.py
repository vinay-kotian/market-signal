from typing import Awaitable, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field


class PriceTick(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    instrument: str = Field(min_length=1)
    price: float = Field(allow_inf_nan=False)


class MarketDataProvider(Protocol):
    """Publish a normalized price tick to the configured consumer."""

    async def publish(self, tick: PriceTick) -> None:
        ...


class SimulatedMarketDataProvider:
    def __init__(self, consumer: Callable[[PriceTick], Awaitable[None]]):
        self._consumer = consumer

    async def publish(self, tick: PriceTick) -> None:
        await self._consumer(tick)
