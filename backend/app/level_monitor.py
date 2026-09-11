import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel

from app.level_repository import LevelRepository
from app.market_data import PriceTick


class LevelTriggered(BaseModel):
    id: int
    event_type: Literal["LEVEL_TRIGGERED"] = "LEVEL_TRIGGERED"
    level_id: int
    instrument: str
    level_price: float
    previous_price: Optional[float]
    current_price: float
    triggered_at: datetime


class LevelMonitor:
    def __init__(self, repository: LevelRepository):
        self._repository = repository
        self._previous_prices: dict[str, float] = {}
        self._events: deque[LevelTriggered] = deque(maxlen=100)
        self._next_event_id = 1
        self._lock = asyncio.Lock()

    async def on_tick(self, tick: PriceTick) -> None:
        # Keep reading the baseline, evaluating levels, and updating state together.
        async with self._lock:
            previous = self._previous_prices.get(tick.instrument)
            current = tick.price
            if previous == current:
                return

            levels = self._repository.list_enabled(tick.instrument)
            for level in levels:
                touched = current == level.price
                crossed = previous is not None and (
                    previous < level.price <= current
                    or previous > level.price >= current
                )
                # One event even when both the touch and crossing conditions match.
                if touched or crossed:
                    self._events.append(
                        LevelTriggered(
                            id=self._next_event_id,
                            level_id=level.id,
                            instrument=tick.instrument,
                            level_price=level.price,
                            previous_price=previous,
                            current_price=current,
                            triggered_at=datetime.now(timezone.utc),
                        )
                    )
                    self._next_event_id += 1

            self._previous_prices[tick.instrument] = current

    def recent_events(self) -> list[LevelTriggered]:
        return list(reversed(self._events))
