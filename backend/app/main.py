from datetime import datetime, timezone
from contextlib import asynccontextmanager

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


def create_app(database_path=DEFAULT_DATABASE_PATH, signal_settings=None,
               option_settings=None, option_source=None, trade_settings=None, option_prices=None):
    @asynccontextmanager
    async def lifespan(app):
        initialize_database(app.state.database_path)
        engine = SignalEngine(signal_settings or SignalSettings.from_environment())
        signal_repository = SignalRepository(app.state.database_path)
        option_repository = OptionSelectionRepository(app.state.database_path)
        instruments = option_source or SimulatedOptionInstrumentSource(
            datetime.now(timezone.utc).date()
        )
        selector = OptionSelector(instruments)
        prices = option_prices if option_prices is not None else SimulatedOptionPrices.seeded(instruments)
        trade_repository = TradeRepository(app.state.database_path)
        executor = PaperExecutor(trade_repository, instruments, prices,
                                 trade_settings or TradeSettings.from_environment())
        monitor = LevelMonitor(LevelRepository(app.state.database_path), engine,
                               signal_repository=signal_repository, option_selector=selector,
                               option_settings=option_settings or OptionSettings.from_environment(),
                               option_repository=option_repository, paper_executor=executor)
        app.state.trade_repository = trade_repository
        app.state.paper_executor = executor
        app.state.option_prices = prices
        app.state.option_repository = option_repository
        app.state.signal_repository = signal_repository
        app.state.signal_engine = engine
        app.state.level_monitor = monitor
        app.state.market_data_provider = SimulatedMarketDataProvider(monitor.on_tick)
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.database_path = database_path
    app.include_router(router)
    app.include_router(simulation_router)
    app.include_router(signals_router)
    app.include_router(option_router)
    app.include_router(trade_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
