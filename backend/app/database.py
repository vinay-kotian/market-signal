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
