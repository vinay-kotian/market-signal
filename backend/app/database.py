import sqlite3
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


def initialize_database(database_path):
    with connect(database_path) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS trades (
                trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                option_selection_id INTEGER NOT NULL UNIQUE,
                instrument TEXT NOT NULL, trigger_level REAL NOT NULL,
                direction TEXT NOT NULL, option_symbol TEXT NOT NULL,
                option_type TEXT NOT NULL, strike INTEGER NOT NULL, expiry TEXT NOT NULL,
                lot_size INTEGER NOT NULL CHECK(lot_size > 0),
                number_of_lots INTEGER NOT NULL CHECK(number_of_lots > 0),
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                entry_price REAL NOT NULL CHECK(entry_price > 0), entry_time TEXT NOT NULL,
                trade_mode TEXT NOT NULL CHECK(trade_mode = 'PAPER'),
                status TEXT NOT NULL CHECK(status = 'OPEN')
            )"""
        )
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
