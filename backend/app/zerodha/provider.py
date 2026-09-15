import asyncio
import json
import logging
import struct
from math import isfinite

from app.database import connect
from app.market_data import PriceTick
from app.option_prices import SimulatedOptionPrices


class ZerodhaOptionPrices(SimulatedOptionPrices):
    def __init__(self, instruments, connector):
        super().__init__()
        self.instruments, self.connector = instruments, connector

    async def prepare(self, symbol):
        self._prices.pop(symbol, None)
        contract = self.instruments.option(symbol)
        if contract is None:
            return
        try:
            price = await self.connector.ltp(contract.exchange, symbol)
            if not isinstance(price, bool) and isinstance(price, (int, float)) and isfinite(price) and price > 0:
                self.set_price(symbol, price)
        except Exception:
            logging.getLogger(__name__).warning('Option entry quote unavailable')


class ZerodhaMarketDataProvider:
    def __init__(self, consumer, instruments, connector, levels, trades, socket_factory=None):
        self.consumer, self.instruments, self.connector = consumer, instruments, connector
        self.levels, self.trades = levels, trades
        if socket_factory is None:
            from websockets.asyncio.client import connect as socket_factory
        self.socket_factory = socket_factory
        self.status = 'DISCONNECTED'
        self.socket = None
        self.subscribed = set()
        self.latest = {}

    async def publish(self, tick: PriceTick):
        await self.consumer(tick)
        self.latest[tick.instrument] = tick.price

    def required_tokens(self):
        records = [self.instruments.index(level.instrument) for level in self.levels.list() if level.enabled]
        with connect(self.trades.database_path) as connection:
            records.extend(self.instruments.option(trade.option_symbol) for trade in self.trades.all_open(connection))
        return {r.instrument_token for r in records if r is not None}

    async def refresh_subscriptions(self):
        if self.socket is None:
            return
        required = self.required_tokens()
        added, removed = required - self.subscribed, self.subscribed - required
        if removed:
            await self.socket.send(json.dumps({'a': 'unsubscribe', 'v': sorted(removed)}))
        if added:
            await self.socket.send(json.dumps({'a': 'subscribe', 'v': sorted(added)}))
            await self.socket.send(json.dumps({'a': 'mode', 'v': ['ltp', sorted(added)]}))
        self.subscribed = required

    def normalize_tick(self, token, price):
        if isinstance(token, bool) or not isinstance(token, int):
            return None
        record = self.instruments.by_token(token)
        if (record is None or isinstance(price, bool) or not isinstance(price, (float, int))
                or not isfinite(price) or price <= 0):
            return None
        return PriceTick(instrument=record.underlying if record.instrument_type == 'INDEX' else record.trading_symbol, price=price)

    async def handle_message(self, message):
        if not isinstance(message, bytes) or len(message) < 2:
            return  # Text updates and one-byte heartbeats aren't prices.
        try:
            count = struct.unpack_from('!H', message)[0]
            offset, packets = 2, []
            for _ in range(count):
                size = struct.unpack_from('!H', message, offset)[0]
                offset += 2
                if size not in (8, 28, 32, 44, 184) or offset + size > len(message):
                    raise ValueError('Invalid quote frame')
                token, price = struct.unpack_from('!II', message, offset)
                packets.append((token, price / 100))  # NSE indices/NFO options are in paise.
                offset += size
            if offset != len(message):
                raise ValueError('Trailing quote bytes')
        except (ValueError, struct.error):
            logging.getLogger(__name__).warning('Ignoring malformed Zerodha tick frame')
            return
        for token, price in packets:
            tick = self.normalize_tick(token, price)
            if tick is not None and token in self.subscribed:
                await self.publish(tick)
        await self.refresh_subscriptions()

    def set_status(self, status):
        if self.status != status:
            logging.getLogger(__name__).info('Zerodha market connection: %s', status)
        self.status = status

    async def run(self):
        delay = 1
        while True:
            if not self.connector.authenticated:
                self.set_status('AUTH_REQUIRED')
                await asyncio.sleep(1)
                continue
            if self.instruments.status != 'SYNCED':
                self.set_status('SYNC_REQUIRED')
                await asyncio.sleep(1)
                continue
            try:
                self.set_status('CONNECTING')
                async with self.socket_factory(self.connector.websocket_url(), open_timeout=15,
                                               ping_interval=20, max_size=2**20) as socket:
                    self.socket, self.subscribed = socket, set()
                    await self.refresh_subscriptions()
                    self.set_status('CONNECTED')
                    delay = 1
                    while self.connector.authenticated:
                        try:
                            message = await asyncio.wait_for(socket.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            await self.refresh_subscriptions()
                            continue
                        await self.handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if getattr(getattr(error, 'response', None), 'status_code', None) in (401, 403):
                    self.connector.expire()
                self.set_status('RECONNECTING')  # Never log credential-bearing URLs or exceptions.
            finally:
                self.socket, self.subscribed = None, set()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
