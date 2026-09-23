from datetime import datetime
from contextlib import nullcontext
from math import isfinite

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database import connect
from app.indices import IndexInstrument, SUPPORTED_INDICES
from app.trading_date import utc_now


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
    schema = """CREATE TABLE IF NOT EXISTS index_settings (
        instrument TEXT PRIMARY KEY CHECK(instrument IN ('NIFTY', 'BANKNIFTY', 'SENSEX')),
        initial_arm_distance_points REAL NOT NULL CHECK(initial_arm_distance_points >= 0),
        updated_at TEXT NOT NULL)"""
    existing = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'index_settings'").fetchone()
    if existing and "'SENSEX'" not in existing['sql']:
        # Rebuild the old two-index CHECK constraint without resetting saved values.
        if not connection.in_transaction:
            connection.execute('BEGIN IMMEDIATE')
        connection.execute('ALTER TABLE index_settings RENAME TO index_settings_previous')
        connection.execute(schema)
        connection.execute('INSERT INTO index_settings SELECT * FROM index_settings_previous')
        connection.execute('DROP TABLE index_settings_previous')
    else:
        connection.execute(schema)
    connection.executemany('INSERT OR IGNORE INTO index_settings VALUES (?, 30, ?)',
                           [(symbol, utc_now().isoformat()) for symbol in SUPPORTED_INDICES])
    connection.execute('''CREATE TABLE IF NOT EXISTS underlying_quotes (
        instrument TEXT PRIMARY KEY, price REAL NOT NULL, timestamp TEXT NOT NULL)''')


class IndexSettingsRepository:
    def __init__(self, path):
        self.path = path

    def list(self):
        with connect(self.path) as connection:
            return [IndexSettings(**dict(row)) for row in connection.execute(
                "SELECT * FROM index_settings ORDER BY CASE instrument WHEN 'NIFTY' THEN 0 WHEN 'BANKNIFTY' THEN 1 ELSE 2 END")]

    def distance(self, instrument, connection=None):
        context = connect(self.path) if connection is None else nullcontext(connection)
        with context as connection:
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
