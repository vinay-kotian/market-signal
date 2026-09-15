from typing import Literal, Optional

from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel
from app.paper_report import PaperReportingService, PaperTradingReport

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


class TradeHistory(BaseModel):
    items: list[Trade]
    total: int
    page: int
    page_size: int


class TradeDetail(BaseModel):
    trade: Trade
    events: list[TradeEvent]


@router.get('/reports/paper-trading', response_model=PaperTradingReport)
def paper_report(request: Request):
    return PaperReportingService(request.app.state.trade_repository).report()


@router.get('/trades/history', response_model=TradeHistory)
def trade_history(request: Request, page: int = Query(1, ge=1),
                  page_size: int = Query(20, ge=1, le=100),
                  status: Optional[Literal['OPEN', 'CLOSED']] = None,
                  instrument: Optional[str] = Query(None, min_length=1, max_length=100)):
    return request.app.state.trade_repository.history(page, page_size, status, instrument)


@router.get('/trades/{trade_id}', response_model=TradeDetail)
def trade_detail(trade_id: int, request: Request):
    detail = request.app.state.trade_repository.detail(trade_id)
    if detail is None:
        raise HTTPException(status_code=404, detail='Paper trade not found')
    return detail
