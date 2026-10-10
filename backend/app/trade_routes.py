from datetime import date as TradingDate
from typing import Literal, Optional

from fastapi import APIRouter, Request, Query, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.paper_report import PaperReportingService, PaperTradingReport

from app.trade_models import Trade, TradeEntryResult, TradeClassification, BulkTradeClassification
from app.trade_events import TradeEvent
from app.date_range import date_filters
from app.external_levels import authenticate


router = APIRouter(tags=["paper trades"])


@router.get("/trades", response_model=list[Trade])
def list_trades(request: Request):
    return request.app.state.trade_repository.recent()


@router.get("/trade-entry-results", response_model=list[TradeEntryResult])
def list_entry_results(request: Request):
    return request.app.state.trade_repository.recent_results()


@router.get('/trades/{trade_id}/events', response_model=list[TradeEvent])
def trade_events(trade_id: int, request: Request, filters: dict = Depends(date_filters)):
    return request.app.state.trade_events.for_trade(trade_id, **filters)


class TradeHistory(BaseModel):
    items: list[Trade]
    total: int
    page: int
    page_size: int


class TradeDetail(BaseModel):
    trade: Trade
    events: list[TradeEvent]


def report_filters(from_date: Optional[TradingDate] = None,
                   to_date: Optional[TradingDate] = None,
                   status: Optional[Literal['OPEN', 'CLOSED']] = None,
                   instrument: Optional[str] = Query(None, min_length=1, max_length=100),
                   strategy_type: Optional[Literal['LEGACY', 'ATR']] = None):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail='From Date cannot be after To Date')
    return dict(from_date=from_date, to_date=to_date, status=status, instrument=instrument, strategy_type=strategy_type)


@router.get('/reports/paper-trading', response_model=PaperTradingReport)
def paper_report(request: Request, view: Literal["RAW", "STRATEGY"] = "STRATEGY",
                 filters: dict = Depends(report_filters)):
    return PaperReportingService(request.app.state.trade_repository).report(view, **filters)


@router.get('/reports/strategy-comparison')
def strategy_comparison(request: Request, view: Literal['RAW', 'STRATEGY'] = 'STRATEGY',
                        filters: dict = Depends(report_filters)):
    return PaperReportingService(request.app.state.trade_repository).strategy_comparison(view, **filters)


def export_filters(from_date: str = Query(..., pattern=r'^\d{4}-\d{2}-\d{2}$'),
                   to_date: Optional[str] = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
                   status: Optional[Literal['OPEN', 'CLOSED']] = None,
                   instrument: Optional[str] = Query(None, min_length=1, max_length=100),
                   strategy_type: Optional[Literal['LEGACY', 'ATR']] = None):
    try:
        start = TradingDate.fromisoformat(from_date)
        end = TradingDate.fromisoformat(to_date) if to_date is not None else start
    except ValueError:
        raise HTTPException(422, 'Use valid dates in YYYY-MM-DD format')
    return {**date_filters(start, end), 'status': status, 'instrument': instrument, 'strategy_type': strategy_type}


@router.get('/reports/export', dependencies=[Depends(authenticate)])
def export_report(request: Request, filters: dict = Depends(export_filters),
                  mode: Literal['PAPER', 'BACKTEST'] = 'PAPER',
                  view: Literal['RAW', 'STRATEGY'] = 'RAW'):
    filename = f"trading-report-{mode}-{filters['from_date']}-{filters['to_date']}.csv"
    chunks = PaperReportingService(request.app.state.trade_repository).export_csv(
        mode=mode, view=view, **filters)
    return StreamingResponse(chunks, media_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Cache-Control': 'no-store',
    })


@router.get('/trades/history', response_model=TradeHistory)
def trade_history(request: Request, page: int = Query(1, ge=1),
                  page_size: int = Query(20, ge=1, le=100),
                  view: Literal["RAW", "STRATEGY"] = "STRATEGY",
                  filters: dict = Depends(report_filters)):
    return request.app.state.trade_repository.history(page, page_size, view=view, **filters)


@router.get('/trades/history/ids', response_model=list[int])
def matching_trade_ids(request: Request, view: Literal["RAW", "STRATEGY"] = "STRATEGY",
                       filters: dict = Depends(report_filters)):
    return request.app.state.trade_repository.matching_ids(view=view, **filters)


@router.get('/trades/by-date', response_model=list[Trade])
def trades_by_date(request: Request, date: TradingDate):
    return request.app.state.trade_repository.by_date(date)


@router.patch('/trades/classification/bulk', response_model=list[Trade])
def classify_trades(classification: BulkTradeClassification, request: Request):
    trades = request.app.state.trade_repository.classify_bulk(classification)
    if trades is None:
        raise HTTPException(status_code=404, detail='One or more PAPER trades not found; no trades changed')
    return trades


@router.get('/trades/{trade_id}', response_model=TradeDetail)
def trade_detail(trade_id: int, request: Request):
    detail = request.app.state.trade_repository.detail(trade_id)
    if detail is None:
        raise HTTPException(status_code=404, detail='Paper trade not found')
    return detail


@router.patch('/trades/{trade_id}/classification', response_model=Trade)
def classify_trade(trade_id: int, classification: TradeClassification, request: Request):
    trade = request.app.state.trade_repository.classify(trade_id, classification)
    if trade is None:
        raise HTTPException(status_code=404, detail='Paper trade not found')
    return trade
