"""Authenticated ingestion; strategy state is always assigned by LevelRepository."""
import json
import os
import secrets
from datetime import date
from math import isfinite
from typing import Annotated, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.database import connect
from app.indices import IndexInstrument
from app.levels import get_repository
from app.level_repository import LevelRepository
from app.models import Level, LevelInput
from app.trading_date import trading_date


class ExternalLevelsSettings(BaseModel):
    api_key: SecretStr = SecretStr('')

    @classmethod
    def from_environment(cls):
        return cls(api_key=os.getenv('EXTERNAL_LEVELS_API_KEY', ''))


def authenticate(request: Request, x_api_key: Optional[str] = Header(default=None)):
    expected = request.app.state.external_levels_settings.api_key.get_secret_value()
    if not expected:
        raise HTTPException(503, 'External levels API is not configured')
    if x_api_key is None or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(401, 'Invalid or missing API key')


PositivePrice = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
LevelState = Literal['ACTIVE', 'PENDING_ARM', 'DISARMED', 'EXPIRED']


class ExternalLevelsInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    instrument: IndexInstrument
    levels: List[PositivePrice] = Field(min_length=1, max_length=1000)
    level_date: date
    source: str = Field(min_length=1, max_length=200)

    @field_validator('level_date', mode='before')
    @classmethod
    def calendar_date(cls, value):
        # Reject timestamp numbers/datetimes rather than silently coercing them.
        if not isinstance(value, str):
            raise ValueError('Use a calendar date in YYYY-MM-DD format')
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise ValueError('Use a calendar date in YYYY-MM-DD format')
        return value

    @field_validator('levels', mode='before')
    @classmethod
    def finite_prices(cls, value):
        # Keep validation errors JSON serializable for non-standard NaN/Infinity input.
        if isinstance(value, list):
            return [str(v) if isinstance(v, float) and not isfinite(v) else v for v in value]
        return value


class LevelResult(BaseModel):
    level: float
    status: Literal['CREATED', 'DUPLICATE']
    level_id: int
    level_state: LevelState


class ExternalLevelsResponse(BaseModel):
    instrument: IndexInstrument
    level_date: date
    results: List[LevelResult]


class AuditedLevel(Level):
    source: Optional[str] = None
    created_by: Optional[Literal['EXTERNAL_API']] = None
    request_id: Optional[str] = None
    idempotency_key: Optional[str] = None


def ingest(repository, data, idempotency_key):
    payload = json.dumps(data.model_dump(mode='json'), sort_keys=True, separators=(',', ':'))
    created = []
    with connect(repository.database_path) as connection:
        # Serialize duplicate checks and commit levels, audit, and retry result together.
        connection.execute('BEGIN IMMEDIATE')
        if idempotency_key is not None:
            previous = connection.execute(
                'SELECT payload, response FROM external_level_requests WHERE idempotency_key = ?',
                (idempotency_key,),
            ).fetchone()
            if previous:
                if previous['payload'] != payload:
                    raise HTTPException(409, 'Idempotency-Key was already used for a different request')
                return ExternalLevelsResponse.model_validate_json(previous['response']), []
        timestamp = repository.clock()
        if data.level_date < trading_date(timestamp):
            raise HTTPException(422, 'Past level dates are not accepted by the external API')
        request_id = str(uuid4())
        results = []
        for price in data.levels:
            row = connection.execute(
                'SELECT * FROM levels WHERE instrument = ? AND price = ? AND level_date = ? ORDER BY id LIMIT 1',
                (data.instrument, price, data.level_date.isoformat()),
            ).fetchone()
            if row is not None:
                level = Level(**dict(row))
                status = 'DUPLICATE'
            else:
                level = repository.create(LevelInput(instrument=data.instrument, price=price,
                    enabled=True, level_date=data.level_date), connection=connection, timestamp=timestamp)
                connection.execute("""INSERT INTO external_level_audit
                    (level_id, source, created_by, request_id, created_at) VALUES (?, ?, 'EXTERNAL_API', ?, ?)""",
                    (level.id, data.source, request_id, level.created_at.isoformat()))
                created.append(level)
                status = 'CREATED'
            results.append(LevelResult(level=price, status=status, level_id=level.id, level_state=level.status))
        response = ExternalLevelsResponse(instrument=data.instrument, level_date=data.level_date, results=results)
        connection.execute('INSERT INTO external_level_requests VALUES (?, ?, ?, ?, ?)',
            (request_id, idempotency_key, payload, response.model_dump_json(), timestamp.isoformat()))
    return response, created


router = APIRouter(prefix='/external/levels', tags=['external levels'], dependencies=[Depends(authenticate)])


@router.post('', response_model=ExternalLevelsResponse)
async def create_external_levels(data: ExternalLevelsInput, request: Request,
        idempotency_key: Optional[str] = Header(default=None, min_length=1, max_length=200, pattern=r'^\S+$'),
        repository: LevelRepository = Depends(get_repository)):
    response, created = ingest(repository, data, idempotency_key)
    for level in created:
        request.app.state.websocket_hub.publish('LEVEL_UPDATED', dict(level=level))
    return response


@router.get('', response_model=List[AuditedLevel])
def list_external_levels(instrument: Optional[IndexInstrument] = None,
        level_date: Optional[date] = None, status: Optional[LevelState] = None,
        repository: LevelRepository = Depends(get_repository)):
    with connect(repository.database_path) as connection:
        rows = connection.execute("""SELECT l.*, a.source, a.created_by, a.request_id, r.idempotency_key
            FROM levels l LEFT JOIN external_level_audit a ON a.level_id = l.id
            LEFT JOIN external_level_requests r ON r.request_id = a.request_id
            WHERE (? IS NULL OR l.instrument = ?) AND (? IS NULL OR l.level_date = ?)
            AND (? IS NULL OR l.status = ?) ORDER BY l.id""",
            (instrument, instrument, level_date.isoformat() if level_date else None,
             level_date.isoformat() if level_date else None, status, status)).fetchall()
        return [AuditedLevel(**dict(row)) for row in rows]
