"""Shared trading-calendar date, independent of storage and execution mode."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TRADING_TIMEZONE = ZoneInfo('Asia/Kolkata')


def utc_now():
    return datetime.now(timezone.utc)


def trading_date(timestamp):
    if timestamp.tzinfo is None:
        raise ValueError('Trading timestamps must be timezone-aware')
    return timestamp.astimezone(TRADING_TIMEZONE).date()
