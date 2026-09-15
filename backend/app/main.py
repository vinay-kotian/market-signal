from contextlib import asynccontextmanager
from contextlib import suppress
import asyncio
from pathlib import Path
from app.backtests import BacktestRunner, router as backtest_router

from app.zerodha.session_store import SessionStore
from app.zerodha.connector import MarketSettings, KiteConnector
from app.zerodha.instruments import ZerodhaInstrumentService
from app.zerodha.provider import ZerodhaMarketDataProvider, ZerodhaOptionPrices
from app.zerodha.routes import router as connection_router
from fastapi import FastAPI

from app.database import DEFAULT_DATABASE_PATH, initialize_database
from app.level_monitor import LevelMonitor
from app.level_repository import LevelRepository
from app.levels import router
from app.market_data import SimulatedMarketDataProvider
from app.simulation import router as simulation_router
from app.settings import SignalSettings
from app.signal_engine import SignalEngine
from app.signal_repository import SignalRepository
from app.signals import router as signals_router
from app.option_selector import OptionSelector
from app.option_instruments import SimulatedOptionInstrumentSource
from app.option_repository import OptionSelectionRepository
from app.option_routes import router as option_router
from app.settings import OptionSettings
from app.settings import TradeSettings
from app.option_prices import SimulatedOptionPrices
from app.paper_executor import PaperExecutor
from app.trade_repository import TradeRepository
from app.trade_routes import router as trade_router
from app.position_monitor import PositionMonitor
from app.simulation_flow import SimulationFlow
from app.trade_events import TradeEventRepository
from app.trading_time import TradingTimeRules, MarketCloseService, utc_now


def create_app(database_path=DEFAULT_DATABASE_PATH, signal_settings=None,
               option_settings=None, option_source=None, trade_settings=None, option_prices=None,
               clock=None, market_settings=None, kite_connector=None, socket_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.backtest_runner = BacktestRunner(Path(app.state.database_path).parent / "backtests")
        current_time = clock or utc_now
        execution_settings = trade_settings or TradeSettings.from_environment()
        data_settings = market_settings or MarketSettings.from_environment()
        app.state.market_settings = data_settings
        app.state.zerodha_auth_error = False
        app.state.zerodha_auth_error_detail = None
        app.state.zerodha_login_state = None
        is_zerodha = data_settings.market_data_mode == 'ZERODHA'
        if is_zerodha and execution_settings.trade_mode != 'PAPER':
            raise ValueError('ZERODHA market data requires PAPER execution')
        initialize_database(app.state.database_path, execution_settings.stop_loss_percentage,
                            execution_settings.model_dump())
        engine = SignalEngine(signal_settings or SignalSettings.from_environment())
        signal_repository = SignalRepository(app.state.database_path)
        option_repository = OptionSelectionRepository(app.state.database_path)
        trade_repository = TradeRepository(app.state.database_path)
        app.state.kite = None
        app.state.zerodha_instruments = None
        if is_zerodha:
            app.state.kite = kite_connector or KiteConnector(data_settings, session_store=SessionStore(
                Path(app.state.database_path).with_suffix('.zerodha-session.json'),
                data_settings.api_key.get_secret_value()))
            instruments = ZerodhaInstrumentService(app.state.database_path, app.state.kite)
            app.state.zerodha_instruments = instruments
            prices = ZerodhaOptionPrices(instruments, app.state.kite)
        else:
            instruments = option_source or SimulatedOptionInstrumentSource(current_time().date())
            prices = option_prices if option_prices is not None else SimulatedOptionPrices.seeded(instruments)
            if option_prices is None:
                for symbol, price in trade_repository.saved_option_prices().items():
                    prices.set_price(symbol, price)
        selector = OptionSelector(instruments)
        executor = PaperExecutor(trade_repository, instruments, prices,
                                 execution_settings)
        monitor = LevelMonitor(LevelRepository(app.state.database_path), engine,
                               signal_repository=signal_repository, option_selector=selector,
                               option_settings=option_settings or OptionSettings.from_environment(),
                               option_repository=option_repository, paper_executor=executor,
                               clock=current_time)
        app.state.trade_repository = trade_repository
        app.state.paper_executor = executor
        app.state.option_prices = prices
        app.state.option_repository = option_repository
        app.state.signal_repository = signal_repository
        app.state.signal_engine = engine
        app.state.level_monitor = monitor
        rules = TradingTimeRules(execution_settings)
        positions = PositionMonitor(trade_repository, clock=current_time, time_rules=rules)
        market_close = MarketCloseService(trade_repository, prices, rules, current_time)
        flow = SimulationFlow(monitor, positions, prices, instruments, market_close)
        app.state.simulation_flow = flow
        app.state.market_close = market_close
        app.state.position_monitor = positions
        app.state.trade_events = TradeEventRepository(app.state.database_path)
        app.state.market_data_provider = (
            ZerodhaMarketDataProvider(flow.on_tick, instruments, app.state.kite,
                                      LevelRepository(app.state.database_path), trade_repository, socket_factory)
            if is_zerodha else SimulatedMarketDataProvider(flow.on_tick))
        app.state.connection_lock = asyncio.Lock()
        app.state.zerodha_task = None
        if is_zerodha:
            if app.state.kite.authenticated:
                try:
                    await instruments.sync()
                    flow.refresh_instruments()
                except Exception:
                    import logging
                    logging.getLogger(__name__).warning('Zerodha instrument sync failed; retry from Connection settings')
            app.state.zerodha_task = asyncio.create_task(app.state.market_data_provider.run())
        await market_close.check()
        close_task = asyncio.create_task(market_close.run())
        try:
            yield
        finally:
            if app.state.zerodha_task is not None:
                app.state.zerodha_task.cancel()
                with suppress(asyncio.CancelledError):
                    await app.state.zerodha_task
            if app.state.kite is not None:
                await app.state.kite.close()
            close_task.cancel()
            with suppress(asyncio.CancelledError):
                await close_task

    app = FastAPI(lifespan=lifespan)
    app.state.database_path = database_path
    app.include_router(router)
    app.include_router(simulation_router)
    app.include_router(signals_router)
    app.include_router(option_router)
    app.include_router(trade_router)
    app.include_router(backtest_router)
    app.include_router(connection_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
