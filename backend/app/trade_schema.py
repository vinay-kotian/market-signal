from decimal import Decimal


TRADE_SCHEMA = """CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL, option_selection_id INTEGER NOT NULL UNIQUE,
    instrument TEXT NOT NULL, trigger_level REAL NOT NULL, direction TEXT NOT NULL,
    option_symbol TEXT NOT NULL, option_type TEXT NOT NULL, strike INTEGER NOT NULL,
    expiry TEXT NOT NULL, lot_size INTEGER NOT NULL CHECK(lot_size > 0),
    number_of_lots INTEGER NOT NULL CHECK(number_of_lots > 0),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    entry_price REAL NOT NULL CHECK(entry_price > 0), entry_time TEXT NOT NULL,
    trade_mode TEXT NOT NULL CHECK(trade_mode IN ('PAPER', 'BACKTEST')),
    status TEXT NOT NULL CHECK(status IN ('OPEN', 'CLOSED')),
    stop_loss_percentage REAL NOT NULL,
    initial_stop_loss REAL NOT NULL,
    exit_price REAL, exit_time TEXT, exit_reason TEXT,
    realised_pnl REAL, realised_pnl_percentage REAL
)"""


def stop_price(entry_price, percentage):
    return float(Decimal(str(entry_price)) * (1 - Decimal(str(percentage)) / 100))


def initialize_trades(connection, percentage):
    columns = [row['name'] for row in connection.execute('PRAGMA table_info(trades)')]
    migrated = bool(columns) and 'initial_stop_loss' not in columns
    if migrated:
        # Rebuild the old OPEN-only CHECK constraint and preserve all entry columns/IDs.
        sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name = 'trades'").fetchone()
        connection.execute('ALTER TABLE trades RENAME TO trades_before_stops')
        connection.execute(TRADE_SCHEMA)
        for row in connection.execute('SELECT * FROM trades_before_stops').fetchall():
            values = dict(row)
            values.update(stop_loss_percentage=percentage,
                          initial_stop_loss=stop_price(row['entry_price'], percentage))
            names = ', '.join(values)
            placeholders = ', '.join('?' for _ in values)
            connection.execute(f'INSERT INTO trades ({names}) VALUES ({placeholders})', tuple(values.values()))
        if sequence:
            connection.execute("DELETE FROM sqlite_sequence WHERE name = 'trades'")
            connection.execute("INSERT INTO sqlite_sequence(name, seq) VALUES ('trades', ?)", (sequence['seq'],))
        connection.execute('DROP TABLE trades_before_stops')
    else:
        connection.execute(TRADE_SCHEMA)
    connection.execute("""CREATE TABLE IF NOT EXISTS trade_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL,
        event_type TEXT NOT NULL CHECK(event_type IN ('POSITION_OPENED', 'STOP_LOSS_HIT', 'POSITION_CLOSED')),
        price REAL NOT NULL, timestamp TEXT NOT NULL,
        reconstructed INTEGER NOT NULL DEFAULT 0,
        UNIQUE(trade_id, event_type)
    )""")
    if migrated:
        connection.execute("""INSERT INTO trade_events (trade_id, event_type, price, timestamp, reconstructed)
            SELECT trade_id, 'POSITION_OPENED', entry_price, entry_time, 1 FROM trades""")
