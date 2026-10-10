"""Persist time configuration alongside existing SQLite settings."""
from fastapi import APIRouter, Request

from app.database import connect
from app.settings import TradingTimeConfiguration


def load_trading_time_settings(path, settings):
    with connect(path) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS trading_time_settings (id INTEGER PRIMARY KEY CHECK(id = 1), settings TEXT NOT NULL)')
        row = connection.execute('SELECT settings FROM trading_time_settings WHERE id = 1').fetchone()
    if row:
        saved = TradingTimeConfiguration.model_validate_json(row['settings'])
        return settings.model_copy(update=saved.model_dump())
    return settings


def response(data):
    return dict(configuration=data.model_dump(mode='json'), timezone='Asia/Kolkata',
                windows=dict(entry_allowed_from=data.trading_start_time.isoformat(),
                             entry_allowed_until=data.new_trade_cutoff_time.isoformat(),
                             mandatory_exit_starts=data.mandatory_exit_time.isoformat()))


router = APIRouter(prefix='/settings/trading-time', tags=['settings'])


@router.get('')
def get_settings(request: Request):
    settings = request.app.state.paper_executor.settings
    data = TradingTimeConfiguration(**{key: getattr(settings, key) for key in TradingTimeConfiguration.model_fields})
    return response(data)


@router.put('')
async def update_settings(data: TradingTimeConfiguration, request: Request):
    with connect(request.app.state.database_path) as connection:
        connection.execute('INSERT INTO trading_time_settings VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET settings = excluded.settings',
                           (data.model_dump_json(),))
    executor = request.app.state.paper_executor
    executor.settings = executor.settings.model_copy(update=data.model_dump())
    # Entry, tick monitoring and the scheduler share this one rules instance.
    executor.time_rules.settings = executor.settings
    # Moving the deadline earlier also applies to positions already open.
    await request.app.state.market_close.check()
    return response(data)
