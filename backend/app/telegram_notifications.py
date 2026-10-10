"""Persist PAPER entry alerts and deliver them outside trading transactions."""
import asyncio
import logging
import time
from datetime import timezone

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from app.database import connect
from app.trading_date import TRADING_TIMEZONE


TELEGRAM_URL = 'https://jayantpanhalkar.pythonanywhere.com/api/telegram'
logger = logging.getLogger('uvicorn.error')


def initialize_notifications(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS telegram_settings (
        id INTEGER PRIMARY KEY CHECK(id = 1), enabled INTEGER NOT NULL CHECK(enabled IN (0, 1))
    )''')
    connection.execute('INSERT OR IGNORE INTO telegram_settings VALUES (1, 0)')
    connection.execute('''CREATE TABLE IF NOT EXISTS telegram_notifications (
        trade_id INTEGER PRIMARY KEY, message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt REAL NOT NULL DEFAULT 0, last_error TEXT
    )''')
    connection.execute('''CREATE INDEX IF NOT EXISTS idx_telegram_pending
        ON telegram_notifications(status, next_attempt)''')


def entry_message(trade):
    timestamp = trade.entry_time
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(TRADING_TIMEZONE).strftime('%d %b %Y %H:%M:%S IST')
    return '\n'.join([
        f'PAPER option entry · Trade #{trade.trade_id}',
        f'Index: {trade.instrument}',
        f'Index level touched: {trade.trigger_level:,.2f}',
        f'Direction: {trade.direction.replace("_", " ")}',
        f'Option: {trade.option_symbol}',
        f'Contract: {trade.option_type} · Strike {trade.strike} · Expiry {trade.expiry}',
        f'Entry premium: ₹{trade.entry_price:,.2f}',
        f'Quantity: {trade.quantity} ({trade.number_of_lots} lots × {trade.lot_size})',
        f'Entry value: ₹{trade.entry_price * trade.quantity:,.2f}',
        f'Initial stop premium: ₹{trade.initial_stop_loss:,.2f}',
        f'Entry time: {timestamp}',
        f'Signal #{trade.signal_id} · Selection #{trade.option_selection_id}',
        f'Strategy: {trade.strategy_version}',
    ])


def enqueue_entry(connection, trade):
    if trade.trade_mode != 'PAPER':
        return
    if connection.execute('SELECT enabled FROM telegram_settings WHERE id = 1').fetchone()['enabled']:
        connection.execute('INSERT OR IGNORE INTO telegram_notifications (trade_id, message) VALUES (?, ?)',
                           (trade.trade_id, entry_message(trade)))


class TelegramNotifications:
    """One async worker; persisted pending alerts survive restarts."""
    def __init__(self, path, *, transport=None):
        self.path = path
        self.client = httpx.AsyncClient(timeout=10, transport=transport)

    def settings(self):
        with connect(self.path) as connection:
            enabled = connection.execute('SELECT enabled FROM telegram_settings WHERE id = 1').fetchone()[0]
        return dict(enabled=bool(enabled))

    def update_settings(self, enabled):
        with connect(self.path) as connection:
            connection.execute('UPDATE telegram_settings SET enabled = ? WHERE id = 1', (enabled,))
            if not enabled:
                connection.execute("UPDATE telegram_notifications SET status = 'CANCELLED' WHERE status = 'PENDING'")
        return dict(enabled=enabled)

    async def deliver_next(self):
        with connect(self.path) as connection:
            row = connection.execute('''SELECT * FROM telegram_notifications
                WHERE status = 'PENDING' AND next_attempt <= ?
                AND (SELECT enabled FROM telegram_settings WHERE id = 1) = 1
                ORDER BY trade_id LIMIT 1''', (time.time(),)).fetchone()
        if row is None:
            return False
        attempts = row['attempts'] + 1
        error_name = None
        try:
            response = await self.client.post(TELEGRAM_URL, json={'message': row['message']})
            response.raise_for_status()
            if response.json().get('sent') is not True:
                raise ValueError('Telegram relay did not confirm delivery')
            status = 'SENT'
        except (httpx.HTTPError, ValueError, AttributeError) as error:
            error_name = type(error).__name__
            status = 'FAILED' if attempts >= 3 else 'PENDING'
            logger.warning('Telegram entry notification failed: trade_id=%s error=%s attempt=%s',
                           row['trade_id'], error_name, attempts)
        with connect(self.path) as connection:
            connection.execute('''UPDATE telegram_notifications
                SET status = ?, attempts = ?, next_attempt = ?, last_error = ?
                WHERE trade_id = ? AND status = 'PENDING' ''',
                (status, attempts, time.time() + 30 * attempts, error_name, row['trade_id']))
        return True

    async def run(self):
        while True:
            try:
                delivered = await self.deliver_next()
            except Exception as error:
                logger.warning('Telegram worker failed: error=%s', type(error).__name__)
                delivered = False
            await asyncio.sleep(0 if delivered else 1)

    async def close(self):
        await self.client.aclose()


class TelegramSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool


router = APIRouter(prefix='/settings/telegram', tags=['settings'])


@router.get('', response_model=TelegramSettings)
def get_settings(request: Request):
    return request.app.state.telegram_notifications.settings()


@router.put('', response_model=TelegramSettings)
def update_settings(data: TelegramSettings, request: Request):
    return request.app.state.telegram_notifications.update_settings(data.enabled)
