from datetime import datetime, timezone
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


def as_utc(value: datetime, naive_timezone=UTC) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=naive_timezone).astimezone(UTC)
    return value.astimezone(UTC)


def iso_utc(value: datetime, naive_timezone=UTC) -> str:
    return as_utc(value, naive_timezone=naive_timezone).isoformat()


def display_ist_time(value: datetime, naive_timezone=UTC) -> str:
    return as_utc(value, naive_timezone=naive_timezone).astimezone(IST).strftime("%H:%M:%S IST")
