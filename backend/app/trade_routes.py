from fastapi import APIRouter, Request

from app.trade_models import Trade, TradeEntryResult
from app.trade_events import TradeEvent


router = APIRouter(tags=["paper trades"])


@router.get("/trades", response_model=list[Trade])
def list_trades(request: Request):
    return request.app.state.trade_repository.recent()


@router.get("/trade-entry-results", response_model=list[TradeEntryResult])
def list_entry_results(request: Request):
    return request.app.state.trade_repository.recent_results()


@router.get('/trades/{trade_id}/events', response_model=list[TradeEvent])
def trade_events(trade_id: int, request: Request):
    return request.app.state.trade_events.for_trade(trade_id)
