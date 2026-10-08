"""Persist trade-derived watchlist membership; trades and quotes remain authoritative."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.database import connect
from app.trading_date import trading_date


class OptionWatchlistItem(BaseModel):
    option_symbol: str
    instrument: str
    strike: int
    expiry: str
    option_type: Literal['CE', 'PE']
    trade_id: int
    trade_mode: Literal['PAPER', 'LIVE']
    entry_time: datetime
    entry_price: float
    current_ltp: Optional[float]
    quote_timestamp: Optional[datetime]
    change_from_entry_percentage: Optional[float]
    unrealized_pnl_percentage: Optional[float]
    realised_pnl_percentage: Optional[float]
    quantity: int
    status: Literal['ACTIVE', 'CLOSED']
    watchlist_date: str


def initialize_option_watchlist(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS option_watchlist (
        option_symbol TEXT PRIMARY KEY,
        trade_id INTEGER NOT NULL,
        watchlist_date TEXT NOT NULL,
        added_at TEXT NOT NULL,
        removed_at TEXT)''')


def watch_trade_entry(trade, connection):
    if trade.trade_mode not in ('PAPER', 'LIVE') or trade.status != 'OPEN':
        return
    connection.execute('''INSERT INTO option_watchlist
        (option_symbol, trade_id, watchlist_date, added_at, removed_at)
        VALUES (?, ?, ?, ?, NULL) ON CONFLICT(option_symbol) DO UPDATE SET
        trade_id = excluded.trade_id, watchlist_date = excluded.watchlist_date,
        added_at = excluded.added_at, removed_at = NULL''',
        (trade.option_symbol, trade.trade_id, trading_date(trade.entry_time).isoformat(), trade.entry_time.isoformat()))


def watch_trade_closed(trade, timestamp, connection):
    if trade.trade_mode in ('PAPER', 'LIVE'):
        connection.execute('''UPDATE option_watchlist SET watchlist_date = ?
            WHERE option_symbol = ? AND trade_id = ?''',
            (trading_date(timestamp).isoformat(), trade.option_symbol, trade.trade_id))


class OptionWatchlistRepository:
    def __init__(self, database_path, clock=None):
        self.path = database_path
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def backfill(self):
        """Migrate existing PAPER trades once; never resurrect manually removed rows."""
        today = trading_date(self.clock()).isoformat()
        with connect(self.path) as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute("""SELECT * FROM trades WHERE trade_mode IN ('PAPER', 'LIVE')
                ORDER BY CASE status WHEN 'OPEN' THEN 0 ELSE 1 END, trade_id DESC""").fetchall()
            for row in rows:
                timestamp = datetime.fromisoformat((row['exit_time'] or row['entry_time']).replace('Z', '+00:00'))
                day = trading_date(timestamp).isoformat()
                if row['status'] == 'OPEN' or day == today:
                    connection.execute('''INSERT OR IGNORE INTO option_watchlist
                        (option_symbol, trade_id, watchlist_date, added_at)
                        VALUES (?, ?, ?, ?)''', (row['option_symbol'], row['trade_id'], day, row['entry_time']))

    def list(self, connection=None):
        if connection is None:
            with connect(self.path) as connection:
                return self.list(connection)
        today = trading_date(self.clock()).isoformat()
        rows = connection.execute('''SELECT w.watchlist_date, t.*, q.price AS current_ltp,
            q.timestamp AS quote_timestamp FROM option_watchlist w
            JOIN trades t ON t.trade_id = w.trade_id AND t.option_symbol = w.option_symbol
            LEFT JOIN simulated_option_quotes q ON q.symbol = w.option_symbol
            WHERE w.removed_at IS NULL AND t.trade_mode IN ('PAPER', 'LIVE')
            AND (t.status = 'OPEN' OR w.watchlist_date = ?)
            ORDER BY CASE t.status WHEN 'OPEN' THEN 0 ELSE 1 END, t.trade_id DESC''', (today,)).fetchall()
        result = []
        for row in rows:
            change = (float((Decimal(str(row['current_ltp'])) / Decimal(str(row['entry_price'])) - 1) * 100)
                      if row['current_ltp'] is not None else None)
            result.append(OptionWatchlistItem(
                option_symbol=row['option_symbol'], instrument=row['instrument'], strike=row['strike'],
                expiry=row['expiry'], option_type=row['option_type'], trade_id=row['trade_id'],
                trade_mode=row['trade_mode'], entry_time=row['entry_time'], entry_price=row['entry_price'],
                current_ltp=row['current_ltp'], quote_timestamp=row['quote_timestamp'],
                change_from_entry_percentage=change,
                unrealized_pnl_percentage=change if row['status'] == 'OPEN' else None,
                realised_pnl_percentage=row['realised_pnl_percentage'], quantity=row['quantity'],
                status='ACTIVE' if row['status'] == 'OPEN' else 'CLOSED', watchlist_date=row['watchlist_date']))
        return result

    def remove(self, symbol):
        with connect(self.path) as connection:
            connection.execute('BEGIN IMMEDIATE')
            item = next((row for row in self.list(connection) if row.option_symbol == symbol), None)
            if item is None:
                return False
            if item.status == 'ACTIVE':
                raise ValueError('Active trade options cannot be removed from the watchlist')
            # A tombstone survives backfill/restart. A new successful entry clears it.
            connection.execute('UPDATE option_watchlist SET removed_at = ? WHERE option_symbol = ?',
                               (self.clock().isoformat(), symbol))
            return True


router = APIRouter(prefix='/watchlist/options', tags=['watchlist'])


@router.get('', response_model=list[OptionWatchlistItem])
def list_options(request: Request):
    return request.app.state.option_watchlist.list()


@router.delete('/{symbol}', status_code=204)
async def remove_option(symbol: str, request: Request):
    try:
        removed = request.app.state.option_watchlist.remove(symbol)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not removed:
        raise HTTPException(status_code=404, detail='Watchlist option not found')
    request.app.state.live_publisher.committed()
    return Response(status_code=204)
