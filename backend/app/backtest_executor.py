"""Historical fills reuse PAPER entry validation and trade construction."""
from contextlib import nullcontext

from app.database import connect
from app.paper_executor import PaperExecutor
from app.trade_models import TradeEntryResult


class HistoricalOptionPrices:
    def __init__(self, clock):
        self.clock = clock
        self.quotes = {}

    def observe(self, symbol, price):
        self.quotes[symbol] = (self.clock(), price)

    def current_price(self, symbol):
        quote = self.quotes.get(symbol)
        # Historical fills never use a quote older than the execution timestamp.
        return quote[1] if quote and quote[0] == self.clock() and quote[1] > 0 else None


class BacktestExecutor(PaperExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending = {}  # One reservation per underlying; no per-instrument threads.
        self.unfilled = []
        self.repository.execution_model = self

    def exit_price(self, trade, observed_price, timestamp, reason):
        # The shared monitor supplies the first observation triggering an exit.
        # Keep fill pricing here so later slippage need not change protection rules.
        return observed_price

    def fail(self, selection, timestamp, reason, connection):
        return self.repository.record_result(TradeEntryResult(
            option_selection_id=selection.id, trade_id=None, status='FAILED',
            failure_reason=reason, timestamp=timestamp), connection)

    def execute(self, signal, selection, timestamp, connection=None):
        context = connect(self.repository.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            if not signal.valid or selection.status != 'SELECTED':
                return None
            if selection.id in [item[1].id for item in self.pending.values()]:
                return None
            existing = self.repository.get_by_selection(selection.id, connection)
            if existing:
                return super().execute(signal, selection, timestamp, connection)
            rejection = self.time_rules.entry_rejection(timestamp)
            if rejection:
                return self.fail(selection, timestamp, rejection, connection)
            if signal.instrument in self.pending or any(
                    trade.instrument == signal.instrument for trade in self.repository.all_open(connection)):
                return self.fail(selection, timestamp, 'ACTIVE_TRADE_EXISTS', connection)
            if self.prices.current_price(selection.option_symbol) is not None:
                return super().execute(signal, selection, timestamp, connection)
            self.pending[signal.instrument] = (signal, selection)
            return None

    def fill_pending(self, symbol, timestamp):
        if self.prices.current_price(symbol) is None:
            return
        for instrument, (signal, selection) in list(self.pending.items()):
            if selection.option_symbol == symbol:
                with connect(self.repository.database_path) as connection:
                    # The shared monitor consumed this signal when it reserved entry.
                    super().execute(signal, selection, timestamp, connection, level_reserved=True)
                del self.pending[instrument]

    def expire_pending(self, timestamp, *, session_end=False):
        for instrument, (signal, selection) in list(self.pending.items()):
            rejection = self.time_rules.entry_rejection(timestamp)
            if rejection or session_end:
                with connect(self.repository.database_path) as connection:
                    self.fail(selection, timestamp, rejection or 'HISTORICAL_OPTION_PRICE_UNAVAILABLE', connection)
                self.unfilled.append((signal, selection))
                del self.pending[instrument]
