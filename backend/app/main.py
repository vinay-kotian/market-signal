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


def create_app(database_path=DEFAULT_DATABASE_PATH, signal_settings=None):
    @asynccontextmanager
    async def lifespan(app):
        initialize_database(app.state.database_path)
        engine = SignalEngine(signal_settings or SignalSettings.from_environment())
        signal_repository = SignalRepository(app.state.database_path)
        monitor = LevelMonitor(LevelRepository(app.state.database_path), engine,
                               signal_repository=signal_repository)
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

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
