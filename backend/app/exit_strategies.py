"""Shared PAPER/BACKTEST exit strategies; broker and entry signals stay separate."""
from decimal import Decimal
from typing import Protocol

from app.exit_settings import AtrSettings
from app.trade_events import TradeEventRepository
from app.trade_schema import stop_price


def decimal(value):
    return Decimal(str(value))


class ExitStrategy(Protocol):
    def initial_stop(self, entry, configuration, option_atr=None): ...
    def protect(self, monitor, trade, price, timestamp, connection): ...


class LegacyExit:
    def initial_stop(self, entry, configuration, option_atr=None):
        percentage = (configuration['initial_stop_loss_pct'] if configuration['stop_strategy'] == 'PROGRESSIVE'
                      else configuration['stop_loss_percentage'])
        return decimal(stop_price(entry, percentage))

    def protect(self, monitor, trade, price, timestamp, connection):
        monitor.update_legacy(trade, price, timestamp, connection)


class AtrExit:
    def initial_stop(self, entry, configuration, option_atr=None):
        settings = AtrSettings(**configuration)
        if option_atr is None or option_atr <= 0:
            raise ValueError('OPTION_ATR_UNAVAILABLE')
        entry, atr = decimal(entry), decimal(option_atr)
        risk = atr * decimal(settings.atr_initial_multiplier)
        if risk >= entry:
            raise ValueError('ATR_STOP_INVALID')
        if settings.atr_max_sl_percent is not None and risk / entry * 100 > decimal(settings.atr_max_sl_percent):
            raise ValueError('ATR_MAX_SL_EXCEEDED')
        activation = self.activation_distance(entry, atr, risk, settings)
        if activation is not None and entry * decimal(settings.atr_breakeven_lock_percent) / 100 >= activation:
            raise ValueError('ATR_BREAKEVEN_CONFIGURATION_INVALID')
        return entry - risk

    def activation_distance(self, entry, atr, risk, settings):
        mode = settings.atr_breakeven_activation_mode
        threshold = decimal(settings.atr_breakeven_activation_threshold)
        if mode == 'OFF':
            return None
        return {'PERCENTAGE': entry / 100, 'ATR': atr, 'R': risk}[mode] * threshold

    def protect(self, monitor, trade, price, timestamp, connection):
        settings = AtrSettings(**trade.strategy_config_snapshot)
        entry, initial, previous, atr = map(decimal, (trade.entry_price, trade.initial_stop_loss,
                                                     trade.current_stop_loss, trade.option_atr_at_entry))
        highest = max(entry, decimal(trade.highest_price), decimal(price))
        trailing = initial
        if settings.atr_trailing_mode == 'PERCENTAGE':
            trailing = highest * (1 - decimal(settings.atr_trailing_percentage) / 100)
        elif settings.atr_trailing_mode == 'ATR':
            trailing = highest - atr * decimal(settings.atr_trailing_multiplier)
        activation = self.activation_distance(entry, atr, entry-initial, settings)
        activated = trade.breakeven_activated or (activation is not None and highest-entry >= activation)
        protected = entry * (1 + decimal(settings.atr_breakeven_lock_percent)/100) if activated else initial
        effective = max(initial, previous, trailing, protected)
        monitor.trades.update_protection(trade, float(highest), float(effective), activated, connection)
        events = TradeEventRepository(monitor.trades.database_path)
        if activated and not trade.breakeven_activated:
            events.record(trade.trade_id, 'BREAKEVEN_PROTECTION_ACTIVATED', price, timestamp, connection,
                          float(previous), float(effective))
        if trailing > max(initial, previous, protected):
            events.record(trade.trade_id, 'TRAILING_STOP_UPDATED', price, timestamp, connection,
                          float(previous), float(effective))
        if decimal(price) <= effective:
            monitor.trades.close_at_stop(trade, price, timestamp, connection, effective_stop=effective)


STRATEGIES = {'LEGACY': LegacyExit(), 'ATR': AtrExit()}


def strategy_for(strategy_type):
    return STRATEGIES[strategy_type]
