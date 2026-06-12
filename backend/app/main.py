from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api.backtests import router as backtests_router
from backend.app.api.dashboard import router as dashboard_router
from backend.app.api.instruments import router as instruments_router
from backend.app.api.levels import router as levels_router
from backend.app.api.realtime import router as realtime_router
from backend.app.api.simulations import router as simulations_router
from backend.app.api.ticks import router as ticks_router
from backend.app.api.trading import router as trading_router
from backend.app.api.zerodha import router as zerodha_router
from backend.app.core.config import settings
from backend.app.db.repositories import archive_past_level_sets
from backend.app.db.session import create_db
from backend.app.db.session import SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    create_db()
    db = SessionLocal()
    try:
        archive_past_level_sets(db, today=date.today())
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(backtests_router)
app.include_router(dashboard_router)
app.include_router(instruments_router)
app.include_router(levels_router)
app.include_router(realtime_router)
app.include_router(simulations_router)
app.include_router(ticks_router)
app.include_router(trading_router)
app.include_router(zerodha_router)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "trading_mode": settings.trading_mode.value,
        "live_trading_enabled": settings.enable_live_trading,
    }


frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
