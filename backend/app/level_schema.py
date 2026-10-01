"""Transactional migration preserving level IDs, state, timestamps and events."""
from datetime import datetime, timezone

from app.trading_date import trading_date

LEVEL_SCHEMA = """CREATE TABLE levels_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL,
    price REAL NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'DISARMED', 'EXPIRED', 'PENDING_ARM')),
    activation_reference_price REAL,
    armed_from TEXT CHECK(armed_from IN ('ABOVE', 'BELOW')),
    level_date TEXT NOT NULL
)"""


def initialize_daily_levels(connection):
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(levels)')}
    needs_arm_migration = 'armed_from' not in columns
    if 'activation_reference_price' not in columns:
        # SQLite requires a rebuild to extend the old status CHECK constraint.
        sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name = 'levels'").fetchone()
        connection.execute(LEVEL_SCHEMA)
        for row in connection.execute('SELECT * FROM levels').fetchall():
            values = dict(row)
            created = datetime.fromisoformat(values['created_at'].replace('Z', '+00:00'))
            # Historical timestamps were written in UTC; tolerate older naive rows.
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            values.setdefault('level_date', trading_date(created).isoformat())
            names = ', '.join(values)
            placeholders = ', '.join('?' for _ in values)
            connection.execute(f'INSERT INTO levels_daily ({names}) VALUES ({placeholders})', tuple(values.values()))
        connection.execute('DROP TABLE levels')
        connection.execute('ALTER TABLE levels_daily RENAME TO levels')
        if sequence:
            connection.execute("DELETE FROM sqlite_sequence WHERE name = 'levels'")
            connection.execute("INSERT INTO sqlite_sequence(name, seq) VALUES ('levels', ?)", (sequence['seq'],))
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(levels)')}
    if 'armed_from' not in columns:
        connection.execute("ALTER TABLE levels ADD COLUMN armed_from TEXT CHECK(armed_from IN ('ABOVE', 'BELOW'))")
    if needs_arm_migration:
        # Old ACTIVE states cannot prove a qualifying arm side.
        connection.execute("UPDATE levels SET status = 'PENDING_ARM' WHERE status = 'ACTIVE'")
    connection.execute('CREATE INDEX IF NOT EXISTS levels_daily_lookup ON levels(level_date, status, instrument)')
