"""Isolated replay orchestration; all trading decisions stay in shared services."""
import json
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import AwareDatetime, Field, model_validator

from app.database import connect, initialize_database
from app.historical_market_data import HistoricalMarketDataProvider, HistoricalTick
from app.level_monitor import LevelMonitor
from app.level_repository import LevelRepository
from app.models import LevelInput
from app.option_instruments import SimulatedOptionInstrumentSource
from app.option_prices import SimulatedOptionPrices
from app.option_repository import OptionSelectionRepository
from app.option_selector import OptionSelector
from app.paper_executor import PaperExecutor
from app.paper_report import calculate_report
from app.position_monitor import PositionMonitor
from app.settings import TradeSettings, SignalSettings, OptionSettings
from app.signal_engine import SignalEngine
from app.signal_repository import SignalRepository
from app.simulation_flow import SimulationFlow
from app.trade_events import TradeEventRepository
from app.trade_repository import TradeRepository
from app.trading_time import MarketCloseService, TradingTimeRules


class BacktestInput(TradeSettings, SignalSettings, OptionSettings):
    trade_mode: Literal['BACKTEST'] = 'BACKTEST'
    instrument: Literal['NIFTY', 'BANKNIFTY']
    levels: list[float] = Field(min_length=1, max_length=100)
    dataset: Optional[list[HistoricalTick]] = Field(default=None, min_length=1, max_length=10000)
    fixture: Optional[Literal['nifty-demo']] = None
    start_time: Optional[AwareDatetime] = None
    end_time: Optional[AwareDatetime] = None

    @model_validator(mode='after')
    def validate_input(self):
        from math import isfinite
        if any(not isfinite(level) or level <= 0 for level in self.levels):
            raise ValueError('Levels must be finite positive prices')
        if (self.dataset is None) == (self.fixture is None):
            raise ValueError('Provide exactly one of dataset or fixture')
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError('start_time must be at or before end_time')
        return self


class ReplayClock:
    def __init__(self, timestamp):
        self.timestamp = timestamp

    def __call__(self):
        return self.timestamp


class BacktestRunner:
    def __init__(self, directory):
        self.directory = Path(directory)

    async def run(self, config: BacktestInput):
        records = config.dataset
        if config.fixture:
            path = Path(__file__).with_name('fixtures') / (config.fixture + '.json')
            records = [HistoricalTick(**row) for row in json.loads(path.read_text())]
        records = sorted([row for row in records
                          if (config.start_time is None or row.timestamp >= config.start_time)
                          and (config.end_time is None or row.timestamp <= config.end_time)],
                         key=lambda row: row.timestamp)
        if not records or not any(row.instrument == config.instrument for row in records):
            raise ValueError('Selected range must include underlying instrument ticks')
        clock = ReplayClock(records[0].timestamp)
        instruments = SimulatedOptionInstrumentSource(
            records[0].timestamp.astimezone(TradingTimeRules.timezone).date())
        allowed = {config.instrument} | {c.symbol for c in instruments.contracts(config.instrument)}
        if any(row.instrument not in allowed for row in records):
            raise ValueError('Dataset contains an unknown instrument or synthetic option symbol')
        run_id = str(uuid4())
        run_directory = self.directory / run_id
        run_directory.mkdir(parents=True)
        path = run_directory / 'results.sqlite3'
        initialize_database(path, config.stop_loss_percentage, config.model_dump())
        with connect(path) as connection:
            connection.execute('CREATE TABLE backtest_run (status TEXT, request TEXT, result TEXT)')
            connection.execute('INSERT INTO backtest_run VALUES (?, ?, ?)',
                               ('RUNNING', config.model_dump_json(), json.dumps(dict(id=run_id, status='RUNNING'))))
        try:
            trades = TradeRepository(path, mode='BACKTEST')
            levels = LevelRepository(path)
            for price in dict.fromkeys(config.levels):
                levels.create(LevelInput(instrument=config.instrument, price=price, enabled=True))
            values = config.model_dump()
            settings = TradeSettings(**{key: values[key] for key in TradeSettings.model_fields})
            signal_settings = SignalSettings(**{key: values[key] for key in SignalSettings.model_fields})
            option_settings = OptionSettings(**{key: values[key] for key in OptionSettings.model_fields})
            prices = SimulatedOptionPrices()  # No invented quotes or future observations.
            executor = PaperExecutor(trades, instruments, prices, settings)
            monitor = LevelMonitor(levels, SignalEngine(signal_settings), clock,
                signal_repository=SignalRepository(path), option_selector=OptionSelector(instruments),
                option_settings=option_settings, option_repository=OptionSelectionRepository(path),
                paper_executor=executor)
            rules = TradingTimeRules(settings)
            positions = PositionMonitor(trades, clock, rules)
            closing = MarketCloseService(trades, prices, rules, clock)
            flow = SimulationFlow(monitor, positions, prices, instruments, closing)

            async def advance(timestamp):
                # Replay timer deadlines before consuming later quotes, avoiding lookahead.
                with connect(path) as connection:
                    deadlines = sorted({rules.exit_deadline(trade) for trade in trades.all_open(connection)})
                for deadline in deadlines:
                    if clock.timestamp <= deadline <= timestamp:
                        clock.timestamp = deadline
                        await closing.check()
                clock.timestamp = timestamp

            await HistoricalMarketDataProvider(flow.on_tick).replay(records, advance)
            if config.end_time:
                await advance(config.end_time)
            with connect(path) as connection:
                count = connection.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
                signal_count = connection.execute('SELECT COUNT(*) FROM signals').fetchone()[0]
                selection_count = connection.execute('SELECT COUNT(*) FROM option_selections').fetchone()[0]
            report = calculate_report(trades.results()).model_dump(mode='json')
            result = dict(id=run_id, status='COMPLETED', **report,
                          wins=report['winning_trades'], losses=report['losing_trades'],
                          breakeven=report['breakeven_trades'],
                          trades=[trade.model_dump(mode='json') for trade in trades.recent(max(count, 1))],
                          signals=[signal.model_dump(mode='json') for signal in SignalRepository(path).recent(max(signal_count, 1))],
                          option_selections=[row.model_dump(mode='json') for row in OptionSelectionRepository(path).recent(max(selection_count, 1))],
                          entry_results=[row.model_dump(mode='json') for row in trades.recent_results(max(selection_count, 1))],
                          events={str(trade.trade_id): [event.model_dump(mode='json') for event in TradeEventRepository(path).for_trade(trade.trade_id)] for trade in trades.recent(max(count, 1))},
                          ticks_processed=len(records), start_time=records[0].timestamp.isoformat(),
                          end_time=clock.timestamp.isoformat())
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Backtest %s failed', run_id)
            result = dict(id=run_id, status='FAILED', error='Replay failed; inspect backend logs')
        with connect(path) as connection:
            connection.execute('UPDATE backtest_run SET status = ?, result = ?',
                               (result['status'], json.dumps(result)))
        return result

    def get(self, run_id: UUID):
        path = self.directory / str(run_id) / 'results.sqlite3'
        if not path.is_file():
            return None
        with connect(path) as connection:
            return json.loads(connection.execute('SELECT result FROM backtest_run').fetchone()['result'])


router = APIRouter(tags=['backtests'])


@router.post('/backtests/run', status_code=201)
async def run_backtest(config: BacktestInput, request: Request):
    try:
        return await request.app.state.backtest_runner.run(config)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get('/backtests/{run_id}')
def get_backtest(run_id: UUID, request: Request):
    result = request.app.state.backtest_runner.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail='Backtest not found')
    return result
