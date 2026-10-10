"""Persist progressive defaults; open trades retain their entry snapshots."""
from fastapi import APIRouter, Request

from app.database import connect
from app.progressive_stop import ProgressiveSettings


def load_protection_settings(path, settings):
    with connect(path) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS protection_settings (id INTEGER PRIMARY KEY CHECK(id = 1), settings TEXT NOT NULL)')
        row = connection.execute('SELECT settings FROM protection_settings WHERE id = 1').fetchone()
    if row:
        saved = ProgressiveSettings.model_validate_json(row['settings'])
        return settings.model_copy(update={**saved.model_dump(), 'stop_strategy': 'PROGRESSIVE'})
    return settings


router = APIRouter(prefix='/settings/protection', tags=['settings'])


@router.get('', response_model=ProgressiveSettings)
def get_settings(request: Request):
    settings = request.app.state.paper_executor.settings
    return ProgressiveSettings(**{key: getattr(settings, key) for key in ProgressiveSettings.model_fields})


@router.put('', response_model=ProgressiveSettings)
async def update_settings(data: ProgressiveSettings, request: Request):
    with connect(request.app.state.database_path) as connection:
        connection.execute('INSERT INTO protection_settings VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET settings = excluded.settings',
                           (data.model_dump_json(),))
    executor = request.app.state.paper_executor
    executor.settings = executor.settings.model_copy(update={**data.model_dump(), 'stop_strategy': 'PROGRESSIVE'})
    from app.exit_settings import LegacyExitSettings, LEGACY_FIELDS
    with connect(request.app.state.database_path) as connection:
        saved = LegacyExitSettings(**{key: getattr(executor.settings, key) for key in LEGACY_FIELDS})
        connection.execute('INSERT INTO legacy_exit_settings VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET settings=excluded.settings', (saved.model_dump_json(),))
    return data
