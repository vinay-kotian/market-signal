import asyncio
import logging
from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from app.database import connect


def utc_now():
    return datetime.now(timezone.utc)


class TradingTimeRules:
    timezone = ZoneInfo('Asia/Kolkata')

    def __init__(self, settings):
        self.settings = settings

    def local(self, timestamp):
        if timestamp.tzinfo is None:
            raise ValueError('Trading timestamps must be timezone-aware')
        return timestamp.astimezone(self.timezone)

    def entry_rejection(self, timestamp):
        now = self.local(timestamp).time()
        if now < self.settings.trading_start_time:
            return 'BEFORE_TRADING_START'
        if now > self.settings.new_trade_cutoff_time:
            return 'NEW_TRADE_CUTOFF_REACHED'
        return None

    def exit_deadline(self, trade):
        return datetime.combine(self.local(trade.entry_time).date(),
                                self.settings.mandatory_exit_time, self.timezone)

    def exit_due(self, trade, timestamp):
        return self.local(timestamp) >= self.exit_deadline(trade)


class MarketCloseService:
    def __init__(self, trades, prices, rules, clock=utc_now):
        self.trades, self.prices, self.rules, self.clock = trades, prices, rules, clock
        self.on_change = None

    async def check(self):
        timestamp = self.clock()
        changed = False
        with connect(self.trades.database_path) as connection:
            connection.execute('BEGIN IMMEDIATE')
            for trade in self.trades.all_open(connection):
                if not self.rules.exit_due(trade, timestamp):
                    continue
                price = self.trades.last_option_price(trade.option_symbol, connection)
                if price is None:
                    price = self.prices.current_price(trade.option_symbol)
                if price is not None and (not isfinite(price) or price < 0):
                    price = None
                if price is None:
                    # Every existing position has at least its observed entry quote.
                    price = trade.entry_price
                changed = self.trades.close(trade, price, timestamp, 'MARKET_CLOSING_EXIT', connection) or changed
        if changed and self.on_change:
            self.on_change()

    async def run(self):
        while True:
            try:
                await self.check()
            except Exception:
                logging.getLogger(__name__).exception('Mandatory exit check failed; retrying')
            await asyncio.sleep(1)
