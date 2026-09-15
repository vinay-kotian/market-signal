EVENT_SCHEMA = """CREATE TABLE trade_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN (
        'POSITION_OPENED', 'STOP_LOSS_HIT', 'POSITION_CLOSED',
        'TRAILING_STOP_UPDATED', 'BREAKEVEN_PROTECTION_ACTIVATED', 'MARKET_CLOSING_EXIT_TRIGGERED')),
    price REAL NOT NULL, timestamp TEXT NOT NULL,
    reconstructed INTEGER NOT NULL DEFAULT 0,
    previous_stop REAL, current_stop REAL
)"""


def initialize_trailing(connection, settings):
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(trades)')}
    if 'highest_price' not in columns:
        for name, definition in {
            'highest_price': 'REAL NOT NULL DEFAULT 0',
            'current_stop_loss': 'REAL NOT NULL DEFAULT 0',
            'breakeven_activated': 'INTEGER NOT NULL DEFAULT 0',
            'trailing_stop_percentage': 'REAL NOT NULL DEFAULT 10',
            'breakeven_protection_enabled': 'INTEGER NOT NULL DEFAULT 1',
            'breakeven_activation_percent': 'REAL NOT NULL DEFAULT 10',
            'breakeven_lock_percent': 'REAL NOT NULL DEFAULT 0',
        }.items():
            connection.execute(f'ALTER TABLE trades ADD COLUMN {name} {definition}')
        connection.execute("""UPDATE trades SET highest_price = entry_price,
            current_stop_loss = initial_stop_loss, trailing_stop_percentage = ?,
            breakeven_protection_enabled = ?, breakeven_activation_percent = ?,
            breakeven_lock_percent = ?""", (
                settings.get('trailing_stop_percentage', 10),
                settings.get('breakeven_protection_enabled', True),
                settings.get('breakeven_activation_percent', 10),
                settings.get('breakeven_lock_percent', 0),
            ))
    event_columns = {row['name'] for row in connection.execute('PRAGMA table_info(trade_events)')}
    event_sql = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'trade_events'").fetchone()['sql']
    if 'current_stop' not in event_columns or 'MARKET_CLOSING_EXIT_TRIGGERED' not in event_sql:
        connection.execute('ALTER TABLE trade_events RENAME TO trade_events_before_trailing')
        connection.execute(EVENT_SCHEMA)
        columns_to_copy = 'id, trade_id, event_type, price, timestamp, reconstructed'
        if 'current_stop' in event_columns:
            columns_to_copy += ', previous_stop, current_stop'
        connection.execute(f'INSERT INTO trade_events ({columns_to_copy}) SELECT {columns_to_copy} FROM trade_events_before_trailing')
        connection.execute('DROP TABLE trade_events_before_trailing')
    connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS once_per_trade_event
        ON trade_events(trade_id, event_type) WHERE event_type != 'TRAILING_STOP_UPDATED'""")
    connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS distinct_trailing_stop
        ON trade_events(trade_id, current_stop) WHERE event_type = 'TRAILING_STOP_UPDATED'""")
