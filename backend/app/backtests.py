"""Single-session replay orchestration; decisions remain in shared PAPER services."""
import hashlib
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Depends, Body
from pydantic import AwareDatetime, Field, model_validator

from app.date_range import date_filters, timestamp_scope
from app.backtest_events import BacktestTimeline
from app.backtest_executor import BacktestExecutor, HistoricalOptionPrices
from app.backtest_summary import backtest_summary
from app.database import connect, initialize_database
from app.historical_market_data import (HistoricalMarketDataProvider, HistoricalTick,
    HistoricalContract, HistoricalDataset, HistoricalOptionInstrumentSource, LocalHistoricalDataSource)
from app.level_monitor import LevelMonitor
from app.index_settings import IndexSettingsInput, IndexSettingsRepository
from app.level_repository import LevelRepository
from app.models import LevelInput
from app.option_repository import OptionSelectionRepository
from app.option_selector import OptionSelector
from app.position_monitor import PositionMonitor
from app.settings import TradeSettings, SignalSettings, OptionSettings, LEGACY_TIME_BUFFERS
from app.signal_engine import SignalEngine
from app.signal_repository import SignalRepository
from app.trade_events import TradeEventRepository
from app.trade_repository import TradeRepository
from app.trading_time import TradingTimeRules


class BacktestInput(TradeSettings, SignalSettings, OptionSettings):
    trade_mode: Literal['BACKTEST'] = 'BACKTEST'
    index_settings: dict[Literal['NIFTY', 'BANKNIFTY', 'SENSEX'], IndexSettingsInput] = Field(default_factory=dict)
    trading_date: date
    instrument: Literal['NIFTY', 'BANKNIFTY', 'SENSEX']
    levels: list[float] = Field(min_length=1, max_length=100)
    dataset: Optional[list[HistoricalTick]] = Field(default=None, min_length=1, max_length=100000)
    contracts: list[HistoricalContract] = Field(default_factory=list, max_length=10000)
    fixture: Optional[Literal['nifty-demo']] = None
    start_time: Optional[AwareDatetime] = None
    end_time: Optional[AwareDatetime] = None

    @model_validator(mode='after')
    def validate_input(self):
        from math import isfinite
        if any(not isfinite(level) or level <= 0 for level in self.levels):
            raise ValueError('Levels must be finite positive prices')
        if self.dataset is not None and self.fixture is not None:
            raise ValueError('Choose dataset or fixture, not both')
        if self.dataset is not None and not self.contracts:
            raise ValueError('Recorded ticks require a dated historical option contract catalogue')
        if self.contracts and self.dataset is None:
            raise ValueError('Supply recorded ticks together with contracts')
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError('start_time must be at or before end_time')
        for timestamp in (self.start_time, self.end_time):
            if timestamp and timestamp.astimezone(TradingTimeRules.timezone).date() != self.trading_date:
                raise ValueError('Range timestamps must belong to the selected Asia/Kolkata trading date')
        return self


class ReplayClock:
    def __init__(self, timestamp):
        self.timestamp = timestamp

    def __call__(self):
        return self.timestamp


class BacktestRunner:
    def __init__(self, directory, data_source=None):
        self.directory = Path(directory)
        self.data_source = data_source or LocalHistoricalDataSource(self.directory.parent / 'historical-data')

    async def run(self, config: BacktestInput):
        if config.fixture:
            if config.instrument != 'NIFTY' or config.trading_date != date(2026, 9, 14):
                raise ValueError('Synthetic demo is only for NIFTY on 2026-09-14')
            bundle = HistoricalDataset.model_validate_json(
                (Path(__file__).with_name('fixtures') / 'nifty-demo.json').read_text())
        elif config.dataset is not None:
            bundle = HistoricalDataset(contracts=config.contracts, ticks=config.dataset)
        else:
            bundle = self.data_source.load(config.trading_date, config.instrument)
        session_start = datetime.combine(config.trading_date, config.market_open_time, TradingTimeRules.timezone)
        session_end = datetime.combine(config.trading_date, config.market_close_time, TradingTimeRules.timezone)
        if any(row.timestamp.astimezone(TradingTimeRules.timezone).date() != config.trading_date for row in bundle.ticks):
            raise ValueError('All ticks must belong to the selected Asia/Kolkata trading date')
        if any(c.instrument != config.instrument for c in bundle.contracts):
            raise ValueError('Contract catalogue must belong to the selected instrument')
        if not any(c.expiry >= config.trading_date for c in bundle.contracts):
            raise ValueError('Catalogue must contain contracts unexpired on the historical date')
        allowed = {config.instrument} | {c.symbol for c in bundle.contracts}
        if any(row.instrument not in allowed for row in bundle.ticks):
            raise ValueError('Dataset contains an unknown instrument or option symbol')
        start = max(config.start_time or session_start, session_start)
        end = min(config.end_time or session_end, session_end)
        records = sorted([row for row in bundle.ticks if start <= row.timestamp <= end], key=lambda row: row.timestamp)
        if not records or not any(row.instrument == config.instrument for row in records):
            raise ValueError('Selected session must include underlying instrument ticks')
        if any(row.price <= 0 for row in records if row.instrument == config.instrument):
            raise ValueError('Underlying prices must be positive')
        clock = ReplayClock(start)
        instruments = HistoricalOptionInstrumentSource(bundle.contracts)
        run_id = str(uuid4())
        run_directory = self.directory / run_id
        run_directory.mkdir(parents=True)
        path = run_directory / 'results.sqlite3'
        settings_fields = {*TradeSettings.model_fields, *SignalSettings.model_fields, *OptionSettings.model_fields}
        snapshot = {key: value for key, value in config.model_dump(mode='json').items() if key in settings_fields}
        snapshot.update(timezone='Asia/Kolkata', index_settings={key: value.model_dump(mode='json')
                        for key, value in config.index_settings.items()},
                        contracts=[c.model_dump(mode='json') for c in bundle.contracts])
        dataset_hash = hashlib.sha256(bundle.model_dump_json().encode()).hexdigest()
        created = datetime.now(timezone.utc).isoformat()
        result = dict(id=run_id, status='RUNNING', trading_date=config.trading_date.isoformat(),
                      instrument=config.instrument, strategy_version=config.strategy_version,
                      settings_snapshot=snapshot, input_levels=list(dict.fromkeys(config.levels)),
                      created_at=created, started_at=created, completed_at=None, error_message=None,
                      data_source=bundle.source, dataset_hash=dataset_hash)
        initialize_database(path, config.stop_loss_percentage, config.model_dump())
        with connect(path) as connection:
            connection.execute('''CREATE TABLE backtest_run (
                id TEXT PRIMARY KEY, trading_date TEXT, instrument TEXT, status TEXT,
                created_at TEXT, started_at TEXT, completed_at TEXT, error_message TEXT,
                settings_snapshot TEXT, levels TEXT, request TEXT, result TEXT)''')
            connection.execute('INSERT INTO backtest_run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (run_id, str(config.trading_date), config.instrument, 'RUNNING', created, created, None, None,
                 json.dumps(snapshot), json.dumps(result['input_levels']), config.model_dump_json(), json.dumps(result)))
            connection.execute('CREATE TABLE backtest_contracts (symbol TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            connection.executemany('INSERT INTO backtest_contracts VALUES (?, ?)',
                                  [(c.symbol, c.model_dump_json()) for c in bundle.contracts])
        timeline = BacktestTimeline(path, run_id, clock)
        trades = TradeRepository(path, mode='BACKTEST')
        levels = LevelRepository(path, clock)
        try:
            for instrument, index_config in config.index_settings.items():
                IndexSettingsRepository(path).update(instrument, index_config)
            for price in dict.fromkeys(config.levels):
                levels.create(LevelInput(instrument=config.instrument, price=price, enabled=True))
            values = config.model_dump()
            settings = TradeSettings(**{key: values[key] for key in TradeSettings.model_fields})
            signal_settings = SignalSettings(**{key: values[key] for key in SignalSettings.model_fields})
            option_settings = OptionSettings(**{key: values[key] for key in OptionSettings.model_fields})
            prices = HistoricalOptionPrices(clock)
            executor = BacktestExecutor(trades, instruments, prices, settings, signal_settings, option_settings)
            monitor = LevelMonitor(levels, SignalEngine(signal_settings), clock,
                signal_repository=SignalRepository(path), option_selector=OptionSelector(instruments),
                option_settings=option_settings, option_repository=OptionSelectionRepository(path), paper_executor=executor)
            rules = executor.time_rules
            positions = PositionMonitor(trades, clock, rules)
            timeline.record('MARKET_OPEN', dict(instrument=config.instrument, data_source=bundle.source), timestamp=session_start)

            async def advance(timestamp):
                # Deadlines trigger without using a stale quote; PositionMonitor fills on the next observation.
                timeline.deadlines(trades, rules, timestamp)
                clock.timestamp = timestamp
                executor.expire_pending(timestamp)
                await monitor.reconcile()

            async def consume(tick):
                if tick.instrument == config.instrument:
                    timeline.spot = tick.price
                    await monitor.on_tick(tick)
                else:
                    # Existing positions process this observation before a pending entry fills.
                    await positions.on_tick(tick)
                    prices.observe(tick.instrument, tick.price)
                    executor.fill_pending(tick.instrument, clock())
                    if tick.price == 0:
                        timeline.record('ZERO_OPTION_QUOTE', dict(option_symbol=tick.instrument, option_price=0,
                            reason='Valid for exits; cannot fill an entry'))
                timeline.capture(tick, monitor)

            await HistoricalMarketDataProvider(consume).replay(records, advance)
            await advance(end)
            executor.expire_pending(end, session_end=True)
            timeline.capture(monitor=monitor)
            timeline.record('MARKET_CLOSE', dict(instrument=config.instrument, partial_session=end < session_end), timestamp=end)
            failed_entries = [r for r in trades.recent_results(100000)
                              if r.failure_reason == 'HISTORICAL_OPTION_PRICE_UNAVAILABLE']
            missing_entries = [(signal, selection) for signal, selection in executor.unfilled if not any(
                row.instrument == selection.option_symbol and row.price > 0 and row.timestamp >= signal.timestamp
                for row in records)]
            for _, selection in missing_entries:
                with connect(path) as connection:
                    executor.fail(selection, end, 'HISTORICAL_OPTION_PRICE_UNAVAILABLE', connection)
            timeline.capture(monitor=monitor)
            with connect(path) as connection:
                open_trades = trades.all_open(connection)
            if failed_entries or missing_entries or (open_trades and end >= datetime.combine(config.trading_date, settings.mandatory_exit_time, rules.timezone)):
                raise ValueError('Historical option data incomplete: an entry or mandatory exit has no valid quote '
                                 'at or after its trigger within the selected session')
            result['status'] = 'COMPLETED'
        except Exception as error:
            logging.getLogger(__name__).exception('Backtest %s failed', run_id)
            result.update(status='FAILED', error_message=str(error) if isinstance(error, ValueError)
                          else 'Replay failed; inspect backend logs')
            result['error'] = result['error_message']
            timeline.record('RUN_FAILED', dict(reason=result['error_message']))
        trade_rows = trades.recent(100000)
        signal_rows = SignalRepository(path).recent(100000)
        signals = {signal.id: signal for signal in signal_rows}
        catalogue = {c.symbol: c for c in bundle.contracts}
        result.update(**backtest_summary(trade_rows),
            levels=[level.model_dump(mode='json') for level in levels.list()],
            trades=[{**trade.model_dump(mode='json'), 'signal_timestamp': signals[trade.signal_id].timestamp.isoformat(),
                     'instrument_token': catalogue[trade.option_symbol].instrument_token} for trade in trade_rows],
            signals=[signal.model_dump(mode='json') for signal in signal_rows],
            option_selections=[{**row.model_dump(mode='json'),
                'instrument_token': catalogue[row.option_symbol].instrument_token if row.option_symbol else None}
                for row in OptionSelectionRepository(path).recent(100000)],
            entry_results=[row.model_dump(mode='json') for row in trades.recent_results(100000)],
            events={str(trade.trade_id): [event.model_dump(mode='json') for event in TradeEventRepository(path).for_trade(trade.trade_id)] for trade in trade_rows},
            timeline=timeline.list(), ticks_processed=len(records), start_time=start.isoformat(), end_time=clock().isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat())
        with connect(path) as connection:
            connection.execute('UPDATE backtest_run SET status = ?, completed_at = ?, error_message = ?, result = ?',
                               (result['status'], result['completed_at'], result['error_message'], json.dumps(result)))
        return result

    def get(self, run_id: UUID):
        path = self.directory / str(run_id) / 'results.sqlite3'
        if not path.is_file():
            return None
        with connect(path) as connection:
            return json.loads(connection.execute('SELECT result FROM backtest_run').fetchone()['result'])

    def list(self, from_date=None, to_date=None):
        results = []
        for path in self.directory.glob('*/results.sqlite3'):
            with connect(path) as connection:
                clauses, values = timestamp_scope(connection, 'created_at', from_date, to_date)
                where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
                saved = connection.execute(f'SELECT result FROM backtest_run{where}', values).fetchone()
                if saved is None:
                    continue
                row = json.loads(saved['result'])
            results.append({key: row.get(key) for key in ('id', 'trading_date', 'instrument', 'status', 'created_at', 'total_trades', 'net_pnl')})
        return sorted(results, key=lambda row: row['created_at'] or '', reverse=True)


def current_snapshot(state):
    executor = state.paper_executor
    return {**executor.signal_settings.model_dump(mode='json'), **executor.option_settings.model_dump(mode='json'),
            **executor.settings.model_dump(mode='json'), 'trade_mode': 'BACKTEST',
            'index_settings': {row.instrument: {'initial_arm_distance_points': row.initial_arm_distance_points}
                               for row in IndexSettingsRepository(state.database_path).list()}}


router = APIRouter(tags=['backtests'])


@router.get('/backtests/settings')
def backtest_settings(request: Request):
    return current_snapshot(request.app.state)


@router.get('/backtests')
def list_backtests(request: Request, filters: dict = Depends(date_filters)):
    return request.app.state.backtest_runner.list(**filters)


@router.post('/backtests/run', status_code=201)
async def run_backtest(request: Request, config: dict = Body(...)):
    try:
        # Only explicitly supplied fields override the current application snapshot.
        current = current_snapshot(request.app.state)
        # Validate after merging: partial time overrides depend on the saved session.
        overrides = TradeSettings.preserve_legacy_configuration(config)
        for legacy, buffer in LEGACY_TIME_BUFFERS.items():
            if legacy in overrides and buffer not in overrides:
                current.pop(buffer, None)
        if isinstance(overrides.get('index_settings'), dict):
            overrides = {**overrides, 'index_settings': {**current['index_settings'], **overrides['index_settings']}}
        config = BacktestInput.model_validate({**current, **overrides})
        return await request.app.state.backtest_runner.run(config)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get('/backtests/{run_id}')
def get_backtest(run_id: UUID, request: Request):
    result = request.app.state.backtest_runner.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail='Backtest not found')
    return result
