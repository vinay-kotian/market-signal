from fastapi import APIRouter, Request, HTTPException

from app.level_monitor import LevelTriggered
from app.market_data import MarketDataProvider, PriceTick


router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("/tick")
async def publish_tick(tick: PriceTick, request: Request):
    if request.app.state.market_settings.market_data_mode != 'SIMULATED':
        raise HTTPException(status_code=409, detail='Simulated ticks are disabled in ZERODHA mode')
    provider: MarketDataProvider = request.app.state.market_data_provider
    await provider.publish(tick)
    return {"status": "processed"}


@router.get("/events", response_model=list[LevelTriggered])
async def recent_events(request: Request):
    return request.app.state.level_monitor.recent_events()
