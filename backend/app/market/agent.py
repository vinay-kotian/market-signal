from typing import Optional

from backend.app.dto.trading_dto import MarketContext, Tick


class MarketAgent:
    def build_context(self, tick: Tick, previous_tick: Optional[Tick]) -> MarketContext:
        previous_price = previous_tick.last_price if previous_tick else None
        previous_time = previous_tick.timestamp if previous_tick else None

        if previous_price is None:
            direction = "UNKNOWN"
            velocity = 0.0
        else:
            price_change = tick.last_price - previous_price
            if price_change > 0:
                direction = "UP"
            elif price_change < 0:
                direction = "DOWN"
            else:
                direction = "SIDEWAYS"

            seconds = max((tick.timestamp - previous_time).total_seconds(), 1.0)
            velocity = price_change / seconds

        return MarketContext(
            tick=tick,
            previous_price=previous_price,
            direction=direction,
            velocity_per_second=velocity,
        )
