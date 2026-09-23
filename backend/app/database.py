import sqlite3

from app.level_schema import initialize_daily_levels

from app.trade_metadata import initialize_trade_metadata
from app.trade_schema import initialize_trades
from app.trailing_schema import initialize_trailing
from contextlib import contextmanager
from pathlib import Path


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "levels.sqlite3"


@contextmanager
def connect(database_path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(database_path, stop_loss_percentage=10, trade_settings=None):
    with connect(database_path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        initialize_trades(connection, stop_loss_percentage)
        initialize_trailing(connection, trade_settings or {})
        initialize_trade_metadata(connection)
        connection.execute("""CREATE TABLE IF NOT EXISTS simulated_option_quotes (
            symbol TEXT PRIMARY KEY, price REAL NOT NULL CHECK(price >= 0), timestamp TEXT NOT NULL
        )""")
        # Seed legacy positions with their latest known observation; never replace a saved quote.
        connection.execute("""INSERT INTO simulated_option_quotes(symbol, price, timestamp)
            SELECT option_symbol, COALESCE(exit_price, entry_price), COALESCE(exit_time, entry_time)
            FROM trades WHERE 1 ORDER BY COALESCE(exit_time, entry_time) DESC, trade_id DESC
            ON CONFLICT(symbol) DO NOTHING""")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS trade_entry_results (
                option_selection_id INTEGER PRIMARY KEY,
                trade_id INTEGER,
                status TEXT NOT NULL CHECK(status IN ('OPEN', 'FAILED')),
                failure_reason TEXT,
                timestamp TEXT NOT NULL
            )"""
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS option_selections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL UNIQUE,
                instrument TEXT NOT NULL,
                trigger_price REAL NOT NULL,
                direction TEXT NOT NULL,
                option_type TEXT NOT NULL CHECK (option_type IN ('CE', 'PE')),
                itm_depth INTEGER NOT NULL,
                expiry TEXT,
                atm_strike INTEGER,
                itm_strike INTEGER,
                option_symbol TEXT,
                status TEXT NOT NULL CHECK (status IN ('SELECTED', 'FAILED')),
                failure_reason TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_id INTEGER NOT NULL,
                level_id INTEGER NOT NULL,
                instrument TEXT NOT NULL,
                level REAL NOT NULL,
                trigger_price REAL NOT NULL,
                direction TEXT CHECK (direction IN ('FROM_ABOVE', 'FROM_BELOW')),
                approach_distance REAL,
                valid INTEGER NOT NULL CHECK (valid IN (0, 1)),
                rejection_reason TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument TEXT NOT NULL,
                price REAL NOT NULL,
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        columns = {row['name'] for row in connection.execute('PRAGMA table_info(levels)')}
        if 'status' not in columns:
            connection.execute("ALTER TABLE levels ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'DISARMED'))")
        connection.execute("""CREATE TABLE IF NOT EXISTS level_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('LEVEL_DISARMED', 'LEVEL_REARMED')),
            underlying_price REAL NOT NULL,
            timestamp TEXT NOT NULL,
            trade_id INTEGER
        )""")

        initialize_daily_levels(connection)

        from app.index_settings import initialize_index_settings
        initialize_index_settings(connection)
