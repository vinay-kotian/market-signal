from datetime import datetime, timezone
from math import isfinite
from decimal import Decimal

from app.database import connect
from app.trade_events import TradeEventRepository
from app.progressive_stop import ProgressiveSettings, progressive_stop


class PositionMonitor:
    def __init__(self, trades, clock=None, time_rules=None):
        self.trades = trades
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.time_rules = time_rules

    async def on_tick(self, tick):
        if not isfinite(tick.price) or tick.price < 0:
            raise ValueError('Option price must be finite and nonnegative')
        timestamp = self.clock()
        with connect(self.trades.database_path) as connection:
            # Serialize competing writers, then re-read only OPEN positions.
            connection.execute('BEGIN IMMEDIATE')
            self.trades.record_option_price(tick.instrument, tick.price, timestamp, connection)
            for trade in self.trades.open_for_symbol(tick.instrument, connection):
                if self.time_rules and self.time_rules.exit_due(trade, timestamp):
                    self.trades.close(trade, tick.price, timestamp, 'MARKET_CLOSING_EXIT', connection)
                    continue
                if trade.settings_snapshot.get('stop_strategy') == 'PROGRESSIVE':
                    self.update_progressive(trade, tick.price, timestamp, connection)
                    continue
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
                    self.trades.close_at_stop(trade, tick.price, timestamp, connection,
                                              effective_stop=effective)

    def update_progressive(self, trade, price, timestamp, connection):
        settings = ProgressiveSettings(**{key: trade.settings_snapshot[key]
            for key in ProgressiveSettings.model_fields if key in trade.settings_snapshot})
        protection = progressive_stop(trade.entry_price, trade.highest_price, price,
                                      trade.current_stop_loss, trade.profit_lock_activated, settings)
        stop_changed = protection.stop > Decimal(str(trade.current_stop_loss))
        connection.execute("""UPDATE trades SET highest_price = ?, current_stop_loss = ?,
            profit_lock_activated = ?, trailing_pct = ?, trailing_step = ?,
            stop_updated_at = CASE WHEN ? THEN ? ELSE stop_updated_at END
            WHERE trade_id = ? AND status = 'OPEN' AND trade_mode = ?""",
            (float(protection.highest), float(protection.stop), protection.activated,
             float(protection.trailing_pct) if protection.trailing_pct is not None else None,
             protection.step, stop_changed, timestamp.isoformat(), trade.trade_id, self.trades.mode))
        events = TradeEventRepository(self.trades.database_path)
        kinds = []
        if protection.activated and not trade.profit_lock_activated:
            kinds.append('PROFIT_LOCK_ACTIVATED')
        if protection.step != trade.trailing_step:
            kinds.append('TRAILING_STEP_CHANGED')
        if stop_changed:
            kinds.append('TRAILING_STOP_UPDATED')
        for kind in kinds:
            events.record(trade.trade_id, kind, price, timestamp, connection,
                          trade.current_stop_loss, float(protection.stop), protection=protection)
        if Decimal(str(price)) <= protection.stop:
            self.trades.close_at_stop(trade, price, timestamp, connection, effective_stop=protection.stop)
