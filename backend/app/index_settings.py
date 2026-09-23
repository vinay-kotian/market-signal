from datetime import datetime
from math import isfinite
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database import connect
from app.trading_date import utc_now

IndexInstrument = Literal['NIFTY', 'BANKNIFTY']


class IndexSettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    initial_arm_distance_points: float = Field(ge=0, strict=True, allow_inf_nan=False)

    @field_validator('initial_arm_distance_points', mode='before')
    @classmethod
    def json_safe_number(cls, value):
        # Reject overflow/NaN with a JSON-safe validation error (not a 500).
        return str(value) if isinstance(value, float) and not isfinite(value) else value


class IndexSettings(IndexSettingsInput):
    instrument: IndexInstrument
    updated_at: datetime


def initialize_index_settings(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS index_settings (
        instrument TEXT PRIMARY KEY CHECK(instrument IN ('NIFTY', 'BANKNIFTY')),
        initial_arm_distance_points REAL NOT NULL CHECK(initial_arm_distance_points >= 0),
        updated_at TEXT NOT NULL)""")
    connection.executemany('INSERT OR IGNORE INTO index_settings VALUES (?, 30, ?)',
                           [(symbol, utc_now().isoformat()) for symbol in ('NIFTY', 'BANKNIFTY')])
    connection.execute('''CREATE TABLE IF NOT EXISTS underlying_quotes (
        instrument TEXT PRIMARY KEY, price REAL NOT NULL, timestamp TEXT NOT NULL)''')


class IndexSettingsRepository:
    def __init__(self, path):
        self.path = path

    def list(self):
        with connect(self.path) as connection:
            return [IndexSettings(**dict(row)) for row in connection.execute(
                "SELECT * FROM index_settings ORDER BY CASE instrument WHEN 'NIFTY' THEN 0 ELSE 1 END")]

    def distance(self, instrument):
        with connect(self.path) as connection:
            row = connection.execute('SELECT initial_arm_distance_points FROM index_settings WHERE instrument = ?', (instrument,)).fetchone()
            return row[0] if row else None

    def update(self, instrument, data):
        with connect(self.path) as connection:
            connection.execute('UPDATE index_settings SET initial_arm_distance_points = ?, updated_at = ? WHERE instrument = ?',
                               (data.initial_arm_distance_points, utc_now().isoformat(), instrument))
            return IndexSettings(**dict(connection.execute('SELECT * FROM index_settings WHERE instrument = ?', (instrument,)).fetchone()))


router = APIRouter(prefix='/settings/indexes', tags=['settings'])


@router.get('', response_model=list[IndexSettings])
def list_indexes(request: Request):
    return IndexSettingsRepository(request.app.state.database_path).list()


@router.put('/{instrument}', response_model=IndexSettings)
async def update_index(instrument: IndexInstrument, data: IndexSettingsInput, request: Request):
    saved = IndexSettingsRepository(request.app.state.database_path).update(instrument, data)
    request.app.state.websocket_hub.publish('INDEX_SETTINGS_UPDATED', saved)
    return saved
