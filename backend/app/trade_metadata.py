"""Additive, transactional migration: never infer historical entry settings."""


def initialize_trade_metadata(connection):
    # SQLite cannot widen a CHECK with ALTER COLUMN. Rebuild from its exact schema,
    # preserving all columns, row IDs, indexes, triggers and AUTOINCREMENT sequence.
    schema = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='trades'").fetchone()
    if schema and "CHECK(strategy_type IN ('LEGACY','ATR'))" in schema[0]:
        sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='trades'").fetchone()
        objects = connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='trades' AND sql IS NOT NULL AND type IN ('index','trigger')").fetchall()
        sql = schema[0].replace("CHECK(strategy_type IN ('LEGACY','ATR'))", "CHECK(strategy_type IN ('LEGACY','ATR','ATR_FIXED'))")
        import re
        sql = re.sub(r'^CREATE TABLE (?:IF NOT EXISTS )?["`\[]?trades["`\]]?', 'CREATE TABLE trades_strategy3', sql, count=1, flags=re.IGNORECASE)
        connection.execute(sql)
        connection.execute('INSERT INTO trades_strategy3 SELECT * FROM trades')
        connection.execute('DROP TABLE trades')
        connection.execute('ALTER TABLE trades_strategy3 RENAME TO trades')
        for obj in objects:
            connection.execute(obj[0])
        if sequence:
            connection.execute("UPDATE sqlite_sequence SET seq=? WHERE name='trades'", (sequence[0],))
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(trades)')}
    additions = {
        'strategy3_entry': "TEXT NOT NULL DEFAULT '{}'",
        'strategy_type': "TEXT NOT NULL DEFAULT 'LEGACY' CHECK(strategy_type IN ('LEGACY','ATR','ATR_FIXED'))",
        'strategy_config_snapshot': "TEXT NOT NULL DEFAULT '{}'",
        'option_atr_at_entry': 'REAL', 'index_atr_at_entry': 'REAL',
        'atr_candle_end': 'TEXT', 'atr_data_source': 'TEXT',
        'initial_risk_per_unit': 'REAL', 'initial_risk_amount': 'REAL', 'initial_risk_percent': 'REAL',
        'strategy_version': "TEXT NOT NULL DEFAULT 'UNKNOWN'",
        'validity_status': "TEXT NOT NULL DEFAULT 'MANUAL_REVIEW' CHECK(validity_status IN ('VALID', 'INVALID_STRATEGY_BUG', 'INVALID_DATA_ISSUE', 'INVALID_EXECUTION_ISSUE', 'MANUAL_REVIEW'))",
        'validity_reason': "TEXT DEFAULT 'Legacy trade: entry version and complete settings were not recorded'",
        'exclude_from_strategy_metrics': "INTEGER NOT NULL DEFAULT 0 CHECK(exclude_from_strategy_metrics IN (0, 1))",
        'settings_snapshot': "TEXT NOT NULL DEFAULT '{\"provenance\":\"LEGACY_UNAVAILABLE\"}'",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f'ALTER TABLE trades ADD COLUMN {name} {definition}')
