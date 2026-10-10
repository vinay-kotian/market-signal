from contextlib import nullcontext
from math import isfinite
from decimal import Decimal
from datetime import datetime, timezone

from app.database import connect
from app.index_settings import IndexSettingsRepository
from app.trading_date import trading_date
from app.level_repository import LevelRepository
from app.option_instruments import OptionInstrumentSource
from app.option_prices import OptionPriceSource
from app.settings import TradeSettings, SignalSettings, OptionSettings
from app.trade_models import TradeEntry, TradeEntryResult
from app.trade_repository import TradeRepository
from app.trading_time import TradingTimeRules
from app.exit_settings import AtrSettings, ExitSettingsRepository
from app.exit_strategies import strategy_for
from app.atr_data import AtrData


class PaperExecutor:
    def __init__(self, repository: TradeRepository, instruments: OptionInstrumentSource,
                 prices: OptionPriceSource, settings=None, signal_settings=None, option_settings=None,
                 *, exit_settings=None, atr_data=None, clock=None):
        self.repository = repository
        self.instruments = instruments
        self.prices = prices
        self.settings = settings or TradeSettings()
        self.signal_settings = signal_settings or SignalSettings()
        self.option_settings = option_settings or OptionSettings()
        self.time_rules = TradingTimeRules(self.settings)
        self.exit_settings = exit_settings or ExitSettingsRepository(repository.database_path)
        self.atr_data = atr_data or AtrData(repository.database_path, 'SIMULATED')
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def prepare(self, selection):
        # Fetch external quotes before opening the SQLite write transaction.
        if selection.status == 'SELECTED' and hasattr(self.atr_data, 'prepare'):
            with connect(self.repository.database_path) as connection:
                try:
                    strategy, _ = self.exit_settings.resolve(selection.instrument, self.clock(), connection)
                except ValueError:
                    strategy = None
            if strategy == 'ATR':
                await self.atr_data.prepare(selection.option_symbol, selection.instrument)
        prepare = getattr(self.prices, 'prepare', None)
        if selection.status == 'SELECTED' and prepare is not None:
            await prepare(selection.option_symbol)

    def execute(self, signal, selection, timestamp, connection=None, *, level_reserved=False,
                exit_strategy_override=None):
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
                if level_state['status'] == 'PENDING_ARM':
                    return fail('LEVEL_PENDING_ARM')
                if level_state['status'] == 'EXPIRED' or level_state['level_date'] < trading_date(timestamp).isoformat():
                    return fail('LEVEL_EXPIRED')
                if level_state['level_date'] != trading_date(timestamp).isoformat():
                    return fail('LEVEL_NOT_CURRENT')
            reserved = level_reserved and self.repository.mode == 'BACKTEST'
            if level_state is not None and level_state['status'] == 'DISARMED' and not reserved:
                return fail('LEVEL_DISARMED')
            if self.settings.trade_mode not in ("PAPER", "BACKTEST"):
                return fail("LIVE_MODE_NOT_SUPPORTED")
            if self.settings.trade_mode != self.repository.mode:
                return fail("TRADE_MODE_MISMATCH")
            time_rejection = self.time_rules.entry_rejection(signal.timestamp) or self.time_rules.entry_rejection(timestamp)
            if time_rejection:
                return fail(time_rejection)
            if any(trade.instrument == selection.instrument for trade in self.repository.all_open(connection)):
                return fail('ACTIVE_TRADE_EXISTS')
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
            initial_pct = (self.settings.initial_stop_loss_pct if self.settings.stop_strategy == 'PROGRESSIVE'
                           else self.settings.stop_loss_percentage)
            try:
                strategy, exit_settings = self.exit_settings.resolve(selection.instrument, timestamp, connection,
                                                                      exit_strategy_override)
                option_atr = self.atr_data.value(contract.symbol, timestamp, exit_settings.atr_period, connection)
                index_atr = self.atr_data.value(selection.instrument, timestamp, exit_settings.atr_period, connection)
                configuration = (self.settings.model_dump(mode='json') if strategy == 'LEGACY' else
                                 {key: getattr(exit_settings, key) for key in AtrSettings.model_fields})
                initial_stop = strategy_for(strategy).initial_stop(price, configuration, option_atr['value'])
            except ValueError as error:
                return fail(str(error))
            risk = Decimal(str(price)) - initial_stop
            risk_percent = float(risk / Decimal(str(price)) * 100)
            if strategy == 'ATR':
                initial_pct = risk_percent
            trade = self.repository.save(TradeEntry(
                strategy_type=strategy, strategy_config_snapshot=configuration,
                option_atr_at_entry=option_atr['value'], index_atr_at_entry=index_atr['value'],
                atr_candle_end=option_atr['candle_end'], atr_data_source=option_atr['source'],
                initial_risk_per_unit=float(risk), initial_risk_percent=risk_percent,
                initial_risk_amount=float(risk * contract.lot_size * self.settings.number_of_lots),
                strategy_version=self.settings.strategy_version,
                settings_snapshot={**self.signal_settings.model_dump(mode='json'),
                                   **self.option_settings.model_dump(mode='json'),
                                   **self.settings.model_dump(mode='json'),
                                   'timezone': 'Asia/Kolkata',
                                   'initial_arm_distance_points': IndexSettingsRepository(self.repository.database_path).distance(selection.instrument)},
                trade_mode=self.settings.trade_mode,
                signal_id=signal.id, option_selection_id=selection.id,
                instrument=selection.instrument, trigger_level=signal.level,
                direction=selection.direction, option_symbol=contract.symbol,
                option_type=contract.option_type, strike=contract.strike, expiry=contract.expiry,
                lot_size=contract.lot_size, number_of_lots=self.settings.number_of_lots,
                quantity=contract.lot_size * self.settings.number_of_lots,
                entry_price=price, entry_time=timestamp,
                stop_loss_percentage=initial_pct,
                initial_stop_loss=float(initial_stop),
                highest_price=price,
                current_stop_loss=float(initial_stop),
                trailing_stop_percentage=(self.settings.trailing_stop_percentage if strategy == 'LEGACY' else exit_settings.atr_trailing_percentage),
                breakeven_protection_enabled=(self.settings.breakeven_protection_enabled if strategy == 'LEGACY' else exit_settings.atr_breakeven_activation_mode != 'OFF'),
                breakeven_activation_percent=self.settings.breakeven_activation_percent,
                breakeven_lock_percent=self.settings.breakeven_lock_percent,
            ), connection)
            self.exit_settings.consume_override(selection.instrument, timestamp, connection)
            LevelRepository(self.repository.database_path).change_status(
                signal.level_id, 'DISARMED', signal.trigger_price, timestamp,
                connection=connection, trade_id=trade.trade_id,
            )
            return self.repository.record_result(TradeEntryResult(
                option_selection_id=selection.id, trade_id=trade.trade_id, status="OPEN",
                failure_reason=None, timestamp=trade.entry_time,
            ), connection)
