"""Exact timestamp scopes shared by historical views (legacy naive values are UTC)."""
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from app.trading_date import TRADING_TIMEZONE


def date_filters(from_date: Optional[date] = None, to_date: Optional[date] = None):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail='From Date cannot be after To Date')
    return dict(from_date=from_date, to_date=to_date)


def utc_timestamp(value):
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat(timespec='microseconds')


def timestamp_scope(connection, column, from_date=None, to_date=None):
    if from_date and to_date and from_date > to_date:
        raise ValueError('From Date cannot be after To Date')
    connection.create_function('utc_timestamp', 1, utc_timestamp, deterministic=True)
    clauses, values = [], []
    for boundary, operator, offset in ((from_date, '>=', 0), (to_date, '<', 1)):
        if boundary is not None:
            local_start = datetime.combine(boundary, time.min, TRADING_TIMEZONE)
            try:
                start = local_start.astimezone(timezone.utc) + timedelta(days=offset)
                value = start.isoformat(timespec='microseconds')
            except OverflowError:
                # Python cannot represent the UTC part of the first IST date.
                value = '0000' if offset == 0 else utc_timestamp((local_start + timedelta(days=1)).isoformat())
            clauses.append(f'utc_timestamp({column}) {operator} ?')
            values.append(value)
    return clauses, values
