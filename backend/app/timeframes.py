"""Level metadata only: these durations do not select strategy rules or ATR candles."""
import os
from typing import Annotated
from pydantic import StringConstraints, TypeAdapter

Timeframe = Annotated[str, StringConstraints(pattern=r'^[1-9][0-9]*[mhdw]$')]
DEFAULT_TIMEFRAMES = ('5m', '15m', '1h', '1d')


def timeframe_options():
    # Optional extra durations; defaults remain valid for persisted records.
    extras = [value.strip() for value in os.getenv('LEVEL_TIMEFRAMES', '').split(',') if value.strip()]
    return list(dict.fromkeys([*DEFAULT_TIMEFRAMES, *(TypeAdapter(Timeframe).validate_python(v) for v in extras)]))


def validate_timeframe(value):
    if value is not None and value not in timeframe_options():
        raise ValueError('Choose a configured level timeframe')
