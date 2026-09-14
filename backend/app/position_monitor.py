from datetime import datetime, timezone
from math import isfinite
from decimal import Decimal

from app.database import connect
from app.trade_events import TradeEventRepository


class PositionMonitor:
    def __init__(self, trades, clock=None):
        self.trades = trades
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def on_tick(self, tick):
        if not isfinite(tick.price) or tick.price < 0:
            raise ValueError('Option price must be finite and nonnegative')
        timestamp = self.clock()
        with connect(self.trades.database_path) as connection:
            # Serialize competing writers, then re-read only OPEN positions.
            connection.execute('BEGIN IMMEDIATE')
            for trade in self.trades.open_for_symbol(tick.instrument, connection):
                entry = Decimal(str(trade.entry_price))
                highest = max(Decimal(str(trade.highest_price)), entry, Decimal(str(tick.price)))
                previous = Decimal(str(trade.current_stop_loss))
                initial = Decimal(str(trade.initial_stop_loss))
                trailing = highest * (1 - Decimal(str(trade.trailing_stop_percentage)) / 100)
                threshold = entry * (1 + Decimal(str(trade.breakeven_activation_percent)) / 100)
                activated = trade.breakeven_activated or (
                    trade.breakeven_protection_enabled and highest >= threshold
                )
                protected = entry * (1 + Decimal(str(trade.breakeven_lock_percent)) / 100) if activated else initial
                effective = max(initial, previous, trailing, protected)
                if (highest != Decimal(str(trade.highest_price)) or effective != previous
                        or activated != trade.breakeven_activated):
                    self.trades.update_protection(trade, float(highest), float(effective), activated, connection)
                events = TradeEventRepository(self.trades.database_path)
                if activated and not trade.breakeven_activated:
                    events.record(trade.trade_id, 'BREAKEVEN_PROTECTION_ACTIVATED', tick.price,
                                  timestamp, connection, float(previous), float(effective))
                # Credit trailing only when it exceeds every other stop candidate.
                if trailing > max(initial, previous, protected):
                    events.record(trade.trade_id, 'TRAILING_STOP_UPDATED', tick.price,
                                  timestamp, connection, float(previous), float(effective))
                if Decimal(str(tick.price)) <= effective:
                    self.trades.close_at_stop(trade, tick.price, timestamp, connection)
