"""Shared SQL scope for PAPER reports, history and bulk selection."""
from app.date_range import timestamp_scope


def report_scope(connection, *, mode='PAPER', from_date=None, to_date=None, status=None,
                 instrument=None, view='RAW'):
    if mode not in ('PAPER', 'BACKTEST'):
        raise ValueError('Unknown report mode')
    if from_date and to_date and from_date > to_date:
        raise ValueError('From Date cannot be after To Date')
    if view not in ('RAW', 'STRATEGY'):
        raise ValueError('Unknown report view')
    clauses, values = timestamp_scope(connection, 'entry_time', from_date, to_date)
    clauses.insert(0, 'trade_mode = ?')
    values.insert(0, mode)
    if status is not None:
        clauses.append('status = ?')
        values.append(status)
    if instrument is not None:
        clauses.append('instrument = ?')
        values.append(instrument.strip().upper())
    if view == 'STRATEGY':
        clauses.append('exclude_from_strategy_metrics = 0')
    return ' AND '.join(clauses), values


def paper_scope(connection, **filters):
    return report_scope(connection, mode='PAPER', **filters)
