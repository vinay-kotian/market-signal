from contextlib import nullcontext

from app.database import connect
from app.trade_models import Trade, TradeEntry, TradeEntryResult
from app.trade_events import TradeEventRepository
from decimal import Decimal


class TradeRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    def get_by_selection(self, selection_id, connection):
        row = connection.execute(
            "SELECT * FROM trades WHERE option_selection_id = ?", (selection_id,)
        ).fetchone()
        return Trade(**dict(row)) if row else None

    def save(self, entry: TradeEntry, connection=None) -> Trade:
        context = connect(self.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            values = entry.model_dump(mode="json")
            # Column names come only from the fixed model, never from request data.
            columns = ', '.join(values)
            placeholders = ', '.join('?' for _ in values)
            connection.execute(
                f"INSERT INTO trades ({columns}) VALUES ({placeholders}) "
                "ON CONFLICT(option_selection_id) DO NOTHING", tuple(values.values()),
            )
            trade = self.get_by_selection(entry.option_selection_id, connection)
            TradeEventRepository(self.database_path).record(
                trade.trade_id, 'POSITION_OPENED', trade.entry_price, trade.entry_time, connection,
            )
            return trade

    def open_for_symbol(self, symbol, connection):
        return [Trade(**dict(row)) for row in connection.execute(
            "SELECT * FROM trades WHERE option_symbol = ? AND status = 'OPEN' AND trade_mode = 'PAPER'",
            (symbol,),
        ).fetchall()]

    def has_symbol(self, symbol):
        with connect(self.database_path) as connection:
            return connection.execute('SELECT 1 FROM trades WHERE option_symbol = ? LIMIT 1', (symbol,)).fetchone() is not None

    def update_protection(self, trade, highest, stop, activated, connection):
        connection.execute("""UPDATE trades SET highest_price = ?, current_stop_loss = ?,
            breakeven_activated = ? WHERE trade_id = ? AND status = 'OPEN' AND trade_mode = 'PAPER'""",
            (highest, stop, activated, trade.trade_id))

    def close_at_stop(self, trade, price, timestamp, connection):
        return self.close(trade, price, timestamp, 'STOP_LOSS', connection)

    def all_open(self, connection):
        return [Trade(**dict(row)) for row in connection.execute(
            "SELECT * FROM trades WHERE status = 'OPEN' AND trade_mode = 'PAPER' ORDER BY trade_id"
        ).fetchall()]

    def record_option_price(self, symbol, price, timestamp, connection):
        connection.execute("""INSERT INTO simulated_option_quotes(symbol, price, timestamp)
            VALUES (?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET price = excluded.price,
            timestamp = excluded.timestamp""", (symbol, price, timestamp.isoformat()))

    def last_option_price(self, symbol, connection):
        row = connection.execute('SELECT price FROM simulated_option_quotes WHERE symbol = ?', (symbol,)).fetchone()
        return row['price'] if row else None

    def saved_option_prices(self):
        with connect(self.database_path) as connection:
            return {row['symbol']: row['price'] for row in connection.execute('SELECT symbol, price FROM simulated_option_quotes')}

    def close(self, trade, price, timestamp, reason, connection):
        if reason not in ('STOP_LOSS', 'MARKET_CLOSING_EXIT'):
            raise ValueError('Unknown exit reason')
        entry, exit_price = Decimal(str(trade.entry_price)), Decimal(str(price))
        pnl = float((exit_price - entry) * trade.quantity)
        percentage = float((exit_price - entry) / entry * 100)
        cursor = connection.execute("""UPDATE trades SET status = 'CLOSED', exit_price = ?,
            exit_time = ?, exit_reason = ?, realised_pnl = ?, realised_pnl_percentage = ?
            WHERE trade_id = ? AND trade_mode = 'PAPER' AND status = 'OPEN'""",
            (price, timestamp.isoformat(), reason, pnl, percentage, trade.trade_id))
        if cursor.rowcount:
            events = TradeEventRepository(self.database_path)
            trigger = 'STOP_LOSS_HIT' if reason == 'STOP_LOSS' else 'MARKET_CLOSING_EXIT_TRIGGERED'
            for event_type in [trigger, 'POSITION_CLOSED']:
                events.record(trade.trade_id, event_type, price, timestamp, connection)
        return cursor.rowcount > 0

    def record_result(self, result: TradeEntryResult, connection):
        connection.execute(
            """INSERT INTO trade_entry_results
                (option_selection_id, trade_id, status, failure_reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(option_selection_id) DO UPDATE SET
                    trade_id = excluded.trade_id, status = excluded.status,
                    failure_reason = excluded.failure_reason, timestamp = excluded.timestamp
            """,
            (result.option_selection_id, result.trade_id, result.status,
             result.failure_reason, result.timestamp.isoformat()),
        )
        return result

    def recent(self, limit=100):
        with connect(self.database_path) as connection:
            return [Trade(**dict(row)) for row in connection.execute(
                "SELECT * FROM trades ORDER BY trade_id DESC LIMIT ?", (limit,)
            ).fetchall()]

    def recent_results(self, limit=100):
        with connect(self.database_path) as connection:
            return [TradeEntryResult(**dict(row)) for row in connection.execute(
                "SELECT * FROM trade_entry_results ORDER BY timestamp DESC, option_selection_id DESC LIMIT ?",
                (limit,),
            ).fetchall()]
