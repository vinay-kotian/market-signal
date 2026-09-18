"""Additive, transactional migration: never infer historical entry settings."""


def initialize_trade_metadata(connection):
    columns = {row['name'] for row in connection.execute('PRAGMA table_info(trades)')}
    additions = {
        'strategy_version': "TEXT NOT NULL DEFAULT 'UNKNOWN'",
        'validity_status': "TEXT NOT NULL DEFAULT 'MANUAL_REVIEW' CHECK(validity_status IN ('VALID', 'INVALID_STRATEGY_BUG', 'INVALID_DATA_ISSUE', 'INVALID_EXECUTION_ISSUE', 'MANUAL_REVIEW'))",
        'validity_reason': "TEXT DEFAULT 'Legacy trade: entry version and complete settings were not recorded'",
        'exclude_from_strategy_metrics': "INTEGER NOT NULL DEFAULT 0 CHECK(exclude_from_strategy_metrics IN (0, 1))",
        'settings_snapshot': "TEXT NOT NULL DEFAULT '{\"provenance\":\"LEGACY_UNAVAILABLE\"}'",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f'ALTER TABLE trades ADD COLUMN {name} {definition}')
