from contextlib import nullcontext
from math import isfinite

from app.database import connect
from app.trading_date import trading_date
from app.level_repository import LevelRepository
from app.option_instruments import OptionInstrumentSource
from app.option_prices import OptionPriceSource
from app.settings import TradeSettings, SignalSettings, OptionSettings
from app.trade_models import TradeEntry, TradeEntryResult
from app.trade_repository import TradeRepository
from app.trade_schema import stop_price
from app.trading_time import TradingTimeRules


class PaperExecutor:
    def __init__(self, repository: TradeRepository, instruments: OptionInstrumentSource,
                 prices: OptionPriceSource, settings=None, signal_settings=None, option_settings=None):
        self.repository = repository
        self.instruments = instruments
        self.prices = prices
        self.settings = settings or TradeSettings()
        self.signal_settings = signal_settings or SignalSettings()
        self.option_settings = option_settings or OptionSettings()
        self.time_rules = TradingTimeRules(self.settings)

    async def prepare(self, selection):
        # Fetch external quotes before opening the SQLite write transaction.
        prepare = getattr(self.prices, 'prepare', None)
        if selection.status == 'SELECTED' and prepare is not None:
            await prepare(selection.option_symbol)

    def execute(self, signal, selection, timestamp, connection=None):
        if not signal.valid or selection.status != "SELECTED":
            return None
        if selection.signal_id != signal.id:
            raise ValueError("Selection does not belong to signal")
        context = connect(self.repository.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            existing = self.repository.get_by_selection(selection.id, connection)
            if existing:
                return TradeEntryResult(option_selection_id=selection.id, trade_id=existing.trade_id,
                                        status=existing.status, failure_reason=None, timestamp=existing.entry_time)

            def fail(reason):
                return self.repository.record_result(TradeEntryResult(
                    option_selection_id=selection.id, trade_id=None, status="FAILED",
                    failure_reason=reason, timestamp=timestamp,
                ), connection)

            level_state = connection.execute('SELECT status, level_date FROM levels WHERE id = ?',
                                             (signal.level_id,)).fetchone()
            if level_state is not None:
                if level_state['status'] == 'EXPIRED' or level_state['level_date'] < trading_date(timestamp).isoformat():
                    return fail('LEVEL_EXPIRED')
                if level_state['level_date'] != trading_date(timestamp).isoformat():
                    return fail('LEVEL_NOT_CURRENT')
            if level_state is not None and level_state['status'] == 'DISARMED':
                return fail('LEVEL_DISARMED')
            if self.settings.trade_mode not in ("PAPER", "BACKTEST"):
                return fail("LIVE_MODE_NOT_SUPPORTED")
            if self.settings.trade_mode != self.repository.mode:
                return fail("TRADE_MODE_MISMATCH")
            time_rejection = self.time_rules.entry_rejection(timestamp)
            if time_rejection:
                return fail(time_rejection)
            contract = next((c for c in self.instruments.contracts(selection.instrument)
                             if c.symbol == selection.option_symbol and c.expiry == selection.expiry
                             and c.strike == selection.itm_strike and c.option_type == selection.option_type), None)
            if contract is None:
                return fail("OPTION_CONTRACT_UNAVAILABLE")
            if (isinstance(contract.lot_size, bool) or not isinstance(contract.lot_size, int)
                    or contract.lot_size < 1):
                return fail("INVALID_LOT_SIZE")
            price = self.prices.current_price(contract.symbol)
            if price is None or not isfinite(price) or price <= 0:
                return fail("OPTION_PRICE_UNAVAILABLE")
            self.repository.record_option_price(contract.symbol, price, timestamp, connection)
            trade = self.repository.save(TradeEntry(
                strategy_version=self.settings.strategy_version,
                settings_snapshot={**self.signal_settings.model_dump(mode='json'),
                                   **self.option_settings.model_dump(mode='json'),
                                   **self.settings.model_dump(mode='json'),
                                   'timezone': 'Asia/Kolkata'},
                trade_mode=self.settings.trade_mode,
                signal_id=signal.id, option_selection_id=selection.id,
                instrument=selection.instrument, trigger_level=signal.level,
                direction=selection.direction, option_symbol=contract.symbol,
                option_type=contract.option_type, strike=contract.strike, expiry=contract.expiry,
                lot_size=contract.lot_size, number_of_lots=self.settings.number_of_lots,
                quantity=contract.lot_size * self.settings.number_of_lots,
                entry_price=price, entry_time=timestamp,
                stop_loss_percentage=self.settings.stop_loss_percentage,
                initial_stop_loss=stop_price(price, self.settings.stop_loss_percentage),
                highest_price=price,
                current_stop_loss=stop_price(price, self.settings.stop_loss_percentage),
                trailing_stop_percentage=self.settings.trailing_stop_percentage,
                breakeven_protection_enabled=self.settings.breakeven_protection_enabled,
                breakeven_activation_percent=self.settings.breakeven_activation_percent,
                breakeven_lock_percent=self.settings.breakeven_lock_percent,
            ), connection)
            LevelRepository(self.repository.database_path).change_status(
                signal.level_id, 'DISARMED', signal.trigger_price, timestamp,
                connection=connection, trade_id=trade.trade_id,
            )
            return self.repository.record_result(TradeEntryResult(
                option_selection_id=selection.id, trade_id=trade.trade_id, status="OPEN",
                failure_reason=None, timestamp=trade.entry_time,
            ), connection)
