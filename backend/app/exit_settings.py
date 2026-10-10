"""Selection for future entries; open positions never read these defaults."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator, create_model

from app.settings import TradeSettings
from app.progressive_stop import ProgressiveSettings
from app.database import connect
from app.indices import IndexInstrument, SUPPORTED_INDICES
from app.trading_date import trading_date


StrategyType = Literal['LEGACY', 'ATR']


class AtrSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    atr_period: int = Field(default=14, ge=1, le=200, strict=True)
    atr_timeframe: Literal['5minute'] = '5minute'
    atr_initial_multiplier: float = Field(default=1.5, gt=0, le=20, allow_inf_nan=False)
    atr_trailing_mode: Literal['OFF', 'PERCENTAGE', 'ATR'] = 'OFF'
    atr_trailing_multiplier: float = Field(default=2, gt=0, le=20, allow_inf_nan=False)
    atr_trailing_percentage: float = Field(default=10, gt=0, lt=100, allow_inf_nan=False)
    atr_max_sl_percent: Optional[float] = Field(default=15, gt=0, lt=100, allow_inf_nan=False)
    atr_breakeven_activation_mode: Literal['OFF', 'PERCENTAGE', 'ATR', 'R'] = 'OFF'
    atr_breakeven_activation_threshold: float = Field(default=1, gt=0, allow_inf_nan=False)
    atr_breakeven_lock_percent: float = Field(default=0, ge=0, lt=100, allow_inf_nan=False)


    @model_validator(mode='after')
    def validate_breakeven(self):
        if (self.atr_breakeven_activation_mode == 'PERCENTAGE'
                and self.atr_breakeven_lock_percent >= self.atr_breakeven_activation_threshold):
            raise ValueError('Breakeven lock must be below the activation threshold')
        return self


class ExitSettings(AtrSettings):
    atr_enabled: StrictBool = True
    default_exit_strategy: StrategyType = 'LEGACY'
    instrument_overrides: dict[IndexInstrument, StrategyType] = Field(default_factory=dict)


class DailyExitSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    trading_date: date
    default_exit_strategy: Optional[StrategyType] = None
    instrument_overrides: dict[IndexInstrument, StrategyType] = Field(default_factory=dict)


def initialize_exit_settings(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS exit_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), settings TEXT NOT NULL)''')
    connection.execute('INSERT OR IGNORE INTO exit_settings VALUES (1, ?)', (ExitSettings().model_dump_json(),))
    connection.execute('''CREATE TABLE IF NOT EXISTS daily_exit_selection (
        trading_date TEXT PRIMARY KEY, selection TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS next_trade_exit_selection (
        trading_date TEXT NOT NULL, instrument TEXT NOT NULL, strategy TEXT NOT NULL,
        PRIMARY KEY(trading_date, instrument))''')


class ExitSettingsRepository:
    def __init__(self, path):
        self.path = path

    def load(self, connection):
        return ExitSettings.model_validate_json(connection.execute('SELECT settings FROM exit_settings WHERE id=1').fetchone()[0])

    def daily(self, day, connection):
        row = connection.execute('SELECT selection FROM daily_exit_selection WHERE trading_date=?', (str(day),)).fetchone()
        return DailyExitSelection.model_validate_json(row[0]) if row else DailyExitSelection(trading_date=day)

    def resolve(self, instrument, timestamp, connection, override=None):
        settings = self.load(connection)
        day = trading_date(timestamp)
        daily = self.daily(day, connection)
        queued = connection.execute('SELECT strategy FROM next_trade_exit_selection WHERE trading_date=? AND instrument=?',
                                    (str(day), instrument)).fetchone()
        strategy = (override or (queued[0] if queued else None)
                    or daily.instrument_overrides.get(instrument) or settings.instrument_overrides.get(instrument)
                    or daily.default_exit_strategy or settings.default_exit_strategy)
        if strategy not in ('LEGACY', 'ATR'):
            raise ValueError('UNKNOWN_EXIT_STRATEGY')
        if strategy == 'ATR' and not settings.atr_enabled:
            raise ValueError('ATR_STRATEGY_DISABLED')
        return strategy, settings

    def consume_override(self, instrument, timestamp, connection):
        connection.execute('DELETE FROM next_trade_exit_selection WHERE trading_date=? AND instrument=?',
                           (str(trading_date(timestamp)), instrument))

    def snapshot(self, timestamp):
        day = trading_date(timestamp)
        with connect(self.path) as connection:
            settings = self.load(connection)
            daily = self.daily(day, connection)
            effective = {}
            for symbol in SUPPORTED_INDICES:
                try:
                    effective[symbol] = self.resolve(symbol, timestamp, connection)[0]
                except ValueError:
                    effective[symbol] = 'UNAVAILABLE'
            queued = {row['instrument']: row['strategy'] for row in connection.execute(
                'SELECT instrument,strategy FROM next_trade_exit_selection WHERE trading_date=?', (str(day),))}
        return dict(configuration=settings.model_dump(mode='json'), daily=daily.model_dump(mode='json'),
                    effective=effective, next_trade_overrides=queued, timezone='Asia/Kolkata')


router = APIRouter(prefix='/settings/exit-strategy', tags=['exit strategy'])


@router.get('')
def get_settings(request: Request):
    return request.app.state.exit_settings.snapshot(request.app.state.level_repository.clock())


@router.put('')
def update_settings(data: ExitSettings, request: Request):
    repository = request.app.state.exit_settings
    with connect(repository.path) as connection:
        previous = repository.load(connection)
        if not data.atr_enabled and (
            data.default_exit_strategy == 'ATR' and previous.default_exit_strategy != 'ATR'
            or any(strategy == 'ATR' and previous.instrument_overrides.get(symbol) != 'ATR'
                   for symbol, strategy in data.instrument_overrides.items())):
            raise HTTPException(422, 'ATR is disabled for new selections')
        connection.execute('UPDATE exit_settings SET settings=? WHERE id=1', (data.model_dump_json(),))
    return repository.snapshot(request.app.state.level_repository.clock())


@router.put('/daily')
def update_daily(data: DailyExitSelection, request: Request):
    repository = request.app.state.exit_settings
    with connect(repository.path) as connection:
        settings = repository.load(connection)
        if not settings.atr_enabled and ('ATR' in data.instrument_overrides.values() or data.default_exit_strategy == 'ATR'):
            raise HTTPException(422, 'ATR is disabled for new selections')
        connection.execute('INSERT INTO daily_exit_selection VALUES (?,?) ON CONFLICT(trading_date) DO UPDATE SET selection=excluded.selection',
                           (str(data.trading_date), data.model_dump_json()))
    return repository.snapshot(request.app.state.level_repository.clock())


class TradeExitOverride(BaseModel):
    model_config = ConfigDict(extra='forbid')
    strategy: Optional[StrategyType] = None


@router.put('/next-trade/{instrument}')
def update_next_trade(instrument: IndexInstrument, data: TradeExitOverride, request: Request):
    repository = request.app.state.exit_settings
    timestamp = request.app.state.level_repository.clock()
    day = trading_date(timestamp)
    with connect(repository.path) as connection:
        if data.strategy == 'ATR' and not repository.load(connection).atr_enabled:
            raise HTTPException(422, 'ATR is disabled for new selections')
        connection.execute('DELETE FROM next_trade_exit_selection WHERE trading_date=? AND instrument=?', (str(day), instrument))
        if data.strategy:
            connection.execute('INSERT INTO next_trade_exit_selection VALUES (?,?,?)', (str(day), instrument, data.strategy))
    return repository.snapshot(timestamp)


# Reuse the existing validation and parameter definitions; calculations remain
# in the original Legacy implementation.
LEGACY_FIELDS = (*ProgressiveSettings.model_fields, 'stop_strategy',
    'stop_loss_percentage', 'trailing_stop_percentage', 'breakeven_protection_enabled',
    'breakeven_activation_percent', 'breakeven_lock_percent')
LegacyExitSettings = create_model('LegacyExitSettings', __config__=ConfigDict(extra='forbid'),
    **{name: (TradeSettings.model_fields[name].annotation, TradeSettings.model_fields[name]) for name in LEGACY_FIELDS})


def load_legacy_settings(path, settings):
    with connect(path) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS legacy_exit_settings (id INTEGER PRIMARY KEY CHECK(id=1), settings TEXT NOT NULL)')
        row = connection.execute('SELECT settings FROM legacy_exit_settings WHERE id=1').fetchone()
    return settings.model_copy(update=LegacyExitSettings.model_validate_json(row[0]).model_dump()) if row else settings


@router.get('/legacy', response_model=LegacyExitSettings)
def get_legacy_settings(request: Request):
    settings = request.app.state.paper_executor.settings
    return {name: getattr(settings, name) for name in LEGACY_FIELDS}


@router.put('/legacy', response_model=LegacyExitSettings)
def update_legacy_settings(data: LegacyExitSettings, request: Request):
    executor = request.app.state.paper_executor
    values = data.model_dump()
    try:
        validated = TradeSettings.model_validate({**executor.settings.model_dump(), **values})
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    with connect(request.app.state.database_path) as connection:
        connection.execute('INSERT INTO legacy_exit_settings VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET settings=excluded.settings',
                           (data.model_dump_json(),))
    executor.settings = validated
    return data
