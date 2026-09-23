import json
from datetime import datetime, time
from typing import get_args

from app.trading_date import TRADING_TIMEZONE
from contextlib import nullcontext

from app.database import connect
from app.trade_models import ExitReason, Trade, TradeEntry, TradeEntryResult
from app.trade_events import TradeEventRepository
from decimal import Decimal


class TradeRepository:
    def __init__(self, database_path, mode="PAPER"):
        if mode not in ("PAPER", "BACKTEST"):
            raise ValueError("Only simulated execution modes are supported")
        self.database_path = database_path
        self.mode = mode

    def get_by_selection(self, selection_id, connection):
        row = connection.execute(
            "SELECT * FROM trades WHERE option_selection_id = ?", (selection_id,)
        ).fetchone()
        return Trade(**dict(row)) if row else None

    def save(self, entry: TradeEntry, connection=None) -> Trade:
        if entry.trade_mode != self.mode:
            raise ValueError("Trade mode does not match repository")
        context = connect(self.database_path) if connection is None else nullcontext(connection)
        with context as connection:
            values = entry.model_dump(mode="json")
            values['settings_snapshot'] = json.dumps(values['settings_snapshot'])
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
            "SELECT * FROM trades WHERE option_symbol = ? AND status = 'OPEN' AND trade_mode = ?",
            (symbol, self.mode),
        ).fetchall()]

    def has_symbol(self, symbol):
        with connect(self.database_path) as connection:
            return connection.execute('SELECT 1 FROM trades WHERE option_symbol = ? LIMIT 1', (symbol,)).fetchone() is not None

    def update_protection(self, trade, highest, stop, activated, connection):
        connection.execute("""UPDATE trades SET highest_price = ?, current_stop_loss = ?,
            breakeven_activated = ? WHERE trade_id = ? AND status = 'OPEN' AND trade_mode = ?""",
            (highest, stop, activated, trade.trade_id, self.mode))

    def close_at_stop(self, trade, price, timestamp, connection, *, effective_stop):
        # The monitor may have advanced protection on this tick; its Trade object
        # still contains the earlier stop. Use the exact stop that triggered exit.
        advanced = Decimal(str(effective_stop)) > Decimal(str(trade.initial_stop_loss))
        reason = 'TRAILING_STOP_LOSS' if advanced else 'STOP_LOSS'
        return self.close(trade, price, timestamp, reason, connection)

    def all_open(self, connection):
        return [Trade(**dict(row)) for row in connection.execute(
            "SELECT * FROM trades WHERE status = 'OPEN' AND trade_mode = ? ORDER BY trade_id", (self.mode,)
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
        if reason not in get_args(ExitReason):
            raise ValueError('Unknown exit reason')
        entry, exit_price = Decimal(str(trade.entry_price)), Decimal(str(price))
        pnl = float((exit_price - entry) * trade.quantity)
        percentage = float((exit_price - entry) / entry * 100)
        cursor = connection.execute("""UPDATE trades SET status = 'CLOSED', exit_price = ?,
            exit_time = ?, exit_reason = ?, realised_pnl = ?, realised_pnl_percentage = ?
            WHERE trade_id = ? AND trade_mode = ? AND status = 'OPEN'""",
            (price, timestamp.isoformat(), reason, pnl, percentage, trade.trade_id, self.mode))
        if cursor.rowcount:
            events = TradeEventRepository(self.database_path)
            trigger = {'STOP_LOSS': 'STOP_LOSS_HIT', 'TRAILING_STOP_LOSS': 'STOP_LOSS_HIT',
                       'MARKET_CLOSING_EXIT': 'MARKET_CLOSING_EXIT_TRIGGERED'}.get(reason)
            if trigger:
                events.record(trade.trade_id, trigger, price, timestamp, connection)
            events.record(trade.trade_id, 'POSITION_CLOSED', price, timestamp, connection)
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
                "SELECT * FROM trades WHERE trade_mode = ? ORDER BY trade_id DESC LIMIT ?", (self.mode, limit,)
            ).fetchall()]

    def results(self):
        with connect(self.database_path) as connection:
            return connection.execute(
                "SELECT status, realised_pnl, exclude_from_strategy_metrics FROM trades WHERE trade_mode = ?", (self.mode,)
            ).fetchall()

    def paper_results(self):
        with connect(self.database_path) as connection:
            return connection.execute(
                "SELECT status, realised_pnl, exclude_from_strategy_metrics FROM trades WHERE trade_mode = 'PAPER'"
            ).fetchall()

    def history(self, page=1, page_size=20, status=None, instrument=None):
        clauses, values = ["trade_mode = 'PAPER'"], []
        if status is not None:
            clauses.append('status = ?')
            values.append(status)
        if instrument is not None:
            clauses.append('instrument = ?')
            values.append(instrument.strip().upper())
        where = ' AND '.join(clauses)
        with connect(self.database_path) as connection:
            connection.execute('BEGIN')
            total = connection.execute(f'SELECT COUNT(*) FROM trades WHERE {where}', values).fetchone()[0]
            rows = connection.execute(
                f'SELECT * FROM trades WHERE {where} '
                'ORDER BY julianday(entry_time) DESC, trade_id DESC LIMIT ? OFFSET ?',
                (*values, page_size, (page - 1) * page_size),
            ).fetchall()
            return dict(items=[Trade(**dict(row)) for row in rows], total=total,
                        page=page, page_size=page_size)

    def by_date(self, date):
        start = datetime.combine(date, time.min, TRADING_TIMEZONE)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """SELECT * FROM trades WHERE trade_mode = 'PAPER'
                AND julianday(entry_time) >= julianday(?) AND julianday(entry_time) < julianday(?) + 1
                ORDER BY julianday(entry_time) DESC, trade_id DESC""",
                (start.isoformat(), start.isoformat()),
            ).fetchall()
            return [Trade(**dict(row)) for row in rows]

    def classify_bulk(self, classification):
        ids = list(dict.fromkeys(classification.trade_ids))
        with connect(self.database_path) as connection:
            connection.execute('BEGIN IMMEDIATE')
            # Validate every target before writing. One missing/non-PAPER ID rejects
            # the entire batch, rather than silently applying a partial update.
            rows = [connection.execute(
                "SELECT * FROM trades WHERE trade_id = ? AND trade_mode = 'PAPER'", (trade_id,)
            ).fetchone() for trade_id in ids]
            if any(row is None for row in rows):
                return None
            connection.executemany(
                """UPDATE trades SET validity_status = ?, validity_reason = ?,
                exclude_from_strategy_metrics = ? WHERE trade_id = ? AND trade_mode = 'PAPER'""",
                [(classification.validity_status, classification.reason,
                  classification.exclude_from_strategy_metrics, trade_id) for trade_id in ids],
            )
            return [Trade(**{**dict(row), 'validity_status': classification.validity_status,
                             'validity_reason': classification.reason,
                             'exclude_from_strategy_metrics': classification.exclude_from_strategy_metrics})
                    for row in rows]

    def detail(self, trade_id):
        with connect(self.database_path) as connection:
            connection.execute('BEGIN')
            row = connection.execute(
                "SELECT * FROM trades WHERE trade_id = ? AND trade_mode = ?", (trade_id, self.mode)
            ).fetchone()
            if row is None:
                return None
            return dict(trade=Trade(**dict(row)), events=TradeEventRepository(
                self.database_path).for_trade(trade_id, connection))

    def classify(self, trade_id, classification):
        with connect(self.database_path) as connection:
            cursor = connection.execute("""UPDATE trades SET validity_status = ?,
                validity_reason = ?, exclude_from_strategy_metrics = ?
                WHERE trade_id = ? AND trade_mode = ?""",
                (classification.validity_status, classification.reason,
                 classification.exclude_from_strategy_metrics, trade_id, self.mode))
            if not cursor.rowcount:
                return None
            row = connection.execute('SELECT * FROM trades WHERE trade_id = ?', (trade_id,)).fetchone()
            return Trade(**dict(row))

    def recent_results(self, limit=100):
        with connect(self.database_path) as connection:
            return [TradeEntryResult(**dict(row)) for row in connection.execute(
                "SELECT * FROM trade_entry_results ORDER BY timestamp DESC, option_selection_id DESC LIMIT ?",
                (limit,),
            ).fetchall()]
