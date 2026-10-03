"""Shared SQL scope for PAPER reports, history and bulk selection."""
from datetime import datetime, timezone

from app.trading_date import TRADING_TIMEZONE


def entry_trading_date(value):
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    # Legacy naive entry timestamps were stored in UTC.
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(TRADING_TIMEZONE).date().isoformat()


def paper_scope(connection, *, from_date=None, to_date=None, status=None,
                instrument=None, view='RAW'):
    if from_date and to_date and from_date > to_date:
        raise ValueError('From Date cannot be after To Date')
    if view not in ('RAW', 'STRATEGY'):
        raise ValueError('Unknown report view')
    # SQLite date/julianday rounds fractional seconds. Converting to the local
    # entry date preserves the last microsecond before midnight as well.
    connection.create_function('entry_trading_date', 1, entry_trading_date, deterministic=True)
    clauses, values = ["trade_mode = 'PAPER'"], []
    for boundary, operator in ((from_date, '>='), (to_date, '<=')):
        if boundary is not None:
            clauses.append(f'entry_trading_date(entry_time) {operator} ?')
            values.append(boundary.isoformat())
    if status is not None:
        clauses.append('status = ?')
        values.append(status)
    if instrument is not None:
        clauses.append('instrument = ?')
        values.append(instrument.strip().upper())
    if view == 'STRATEGY':
        clauses.append('exclude_from_strategy_metrics = 0')
    return ' AND '.join(clauses), values
