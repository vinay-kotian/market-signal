from contextlib import nullcontext
from math import isfinite

from app.database import connect
from app.option_instruments import OptionInstrumentSource
from app.option_prices import OptionPriceSource
from app.settings import TradeSettings
from app.trade_models import TradeEntry, TradeEntryResult
from app.trade_repository import TradeRepository


class PaperExecutor:
    def __init__(self, repository: TradeRepository, instruments: OptionInstrumentSource,
                 prices: OptionPriceSource, settings=None):
        self.repository = repository
        self.instruments = instruments
        self.prices = prices
        self.settings = settings or TradeSettings()

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
                                        status="OPEN", failure_reason=None, timestamp=existing.entry_time)

            def fail(reason):
                return self.repository.record_result(TradeEntryResult(
                    option_selection_id=selection.id, trade_id=None, status="FAILED",
                    failure_reason=reason, timestamp=timestamp,
                ), connection)

            if self.settings.trade_mode != "PAPER":
                return fail("LIVE_MODE_NOT_SUPPORTED")
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
            trade = self.repository.save(TradeEntry(
                signal_id=signal.id, option_selection_id=selection.id,
                instrument=selection.instrument, trigger_level=signal.level,
                direction=selection.direction, option_symbol=contract.symbol,
                option_type=contract.option_type, strike=contract.strike, expiry=contract.expiry,
                lot_size=contract.lot_size, number_of_lots=self.settings.number_of_lots,
                quantity=contract.lot_size * self.settings.number_of_lots,
                entry_price=price, entry_time=timestamp,
            ), connection)
            return self.repository.record_result(TradeEntryResult(
                option_selection_id=selection.id, trade_id=trade.trade_id, status="OPEN",
                failure_reason=None, timestamp=trade.entry_time,
            ), connection)
