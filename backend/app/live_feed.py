"""Browser transport and post-commit notifications; no trading decisions live here."""
import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from app.database import connect
from app.signal_models import SignalResult
from app.option_models import StoredOptionSelection
from app.trade_models import Trade, TradeEntryResult

logger = logging.getLogger('uvicorn.error')
router = APIRouter()


def envelope(kind, data):
    return dict(type=kind, timestamp=datetime.now(timezone.utc).isoformat(),
                data=jsonable_encoder(data))


class WebSocketHub:
    """Bounded per-browser buffers prevent a slow browser blocking the strategy."""
    def __init__(self, capacity=256):
        self.clients = set()
        self.capacity = capacity

    def publish(self, kind, data):
        message = envelope(kind, data)
        for queue in tuple(self.clients):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Force reconnect + REST recovery rather than silently dropping a trade.
                self.clients.discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)

    async def serve(self, socket):
        await socket.accept()
        queue = asyncio.Queue(maxsize=self.capacity)
        self.clients.add(queue)
        logger.info('Browser live feed connected; clients=%s', len(self.clients))

        async def send():
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), 20)
                except asyncio.TimeoutError:
                    message = envelope('HEARTBEAT', {})
                if message is None:
                    await socket.close(code=1013, reason='Refresh snapshot and reconnect')
                    return
                await asyncio.wait_for(socket.send_json(message), 5)

        async def receive():
            while True:
                await socket.receive_text()  # Detect disconnect; browser cannot submit trading commands.

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError, OSError, asyncio.TimeoutError):
            pass
        finally:
            self.clients.discard(queue)
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError, OSError, asyncio.TimeoutError):
                    await task
            logger.info('Browser live feed disconnected; clients=%s', len(self.clients))


@router.websocket('/ws/market')
async def market_socket(socket: WebSocket):
    origin = socket.headers.get('origin')
    # Match browser origins, including Vite's same-host proxy in development.
    from urllib.parse import urlsplit
    if origin and (urlsplit(origin).netloc != socket.headers.get('host')
                   and origin.rstrip('/') != socket.app.state.market_settings.frontend_url):
        await socket.close(code=1008)
        return
    await socket.app.state.websocket_hub.serve(socket)


class LiveEventPublisher:
    """Read committed rows after strategy work; never publish rolled-back state.

    Cursors are process-local. Reconnecting browsers recover via REST, not replay.
    Backtests do not construct this publisher and cannot reach the live feed.
    """
    tables = ('signals', 'option_selections', 'level_events', 'trade_events')

    def __init__(self, state):
        self.state = state
        self.hub = state.websocket_hub
        self.path = state.database_path
        self.trigger_id = 0
        with connect(self.path) as c:
            self.cursors = {table: c.execute(f'SELECT COALESCE(MAX(id), 0) FROM {table}').fetchone()[0]
                            for table in self.tables}
        self.trade_states = {}

    def connection(self):
        from app.zerodha.routes import connection_snapshot
        data = connection_snapshot(self.state)
        data.pop('prices', None)
        data.pop('price_changes', None)
        self.hub.publish('ZERODHA_CONNECTION_STATUS', data)

    def committed(self, instrument=None):
        for trigger in reversed(self.state.level_monitor.recent_events()):
            if trigger.id > self.trigger_id:
                self.hub.publish('LEVEL_TRIGGERED', trigger)
                self.trigger_id = trigger.id
        with connect(self.path) as c:
            rows = {table: c.execute(f'SELECT * FROM {table} WHERE id > ? ORDER BY id',
                                    (self.cursors[table],)).fetchall() for table in self.tables}
            for row in rows['signals']:
                self.hub.publish('SIGNAL_CREATED', SignalResult(**dict(row)))
            for row in rows['option_selections']:
                self.hub.publish('OPTION_SELECTION_CREATED', StoredOptionSelection(**dict(row)))
                result = c.execute('SELECT * FROM trade_entry_results WHERE option_selection_id = ?', (row['id'],)).fetchone()
                if result:
                    self.hub.publish('TRADE_ENTRY_RESULT', TradeEntryResult(**dict(result)))
            for row in rows['level_events']:
                level = c.execute('SELECT * FROM levels WHERE id = ?', (row['level_id'],)).fetchone()
                if level:
                    from app.models import Level
                    self.hub.publish(row['event_type'], dict(event=dict(row), level=Level(**dict(level))))
            for row in rows['trade_events']:
                kind = {'POSITION_OPENED': 'TRADE_OPENED', 'POSITION_CLOSED': 'TRADE_CLOSED',
                        'TRAILING_STOP_UPDATED': 'STOP_UPDATED',
                        'BREAKEVEN_PROTECTION_ACTIVATED': 'STOP_UPDATED'}.get(row['event_type'])
                if kind:
                    trade = c.execute("SELECT * FROM trades WHERE trade_id = ? AND trade_mode = 'PAPER'", (row['trade_id'],)).fetchone()
                    if trade:
                        data = Trade(**dict(trade)).model_dump(mode='json')
                        self.hub.publish(kind, data)
                        if data['status'] == 'OPEN':
                            self.trade_states[data['trade_id']] = data
                        else:
                            self.trade_states.pop(data['trade_id'], None)
            # Highest price can change without a stop event. Keep it visible too.
            if instrument:
                for row in c.execute("SELECT * FROM trades WHERE option_symbol = ? AND status = 'OPEN' AND trade_mode = 'PAPER'", (instrument,)):
                    data = Trade(**dict(row)).model_dump(mode='json')
                    if self.trade_states.get(data['trade_id']) != data:
                        self.hub.publish('TRADE_UPDATED', data)
                        self.trade_states[data['trade_id']] = data
            for table in self.tables:
                if rows[table]:
                    self.cursors[table] = rows[table][-1]['id']

    async def on_tick(self, tick):
        await self.state.simulation_flow.on_tick(tick)
        self.committed(tick.instrument)
        provider = self.state.market_data_provider
        previous = self.state.live_prices.get(tick.instrument)
        self.state.live_prices[tick.instrument] = tick.price
        self.state.live_price_changes[tick.instrument] = None if previous is None else tick.price - previous
        self.hub.publish('MARKET_PRICE_UPDATED', dict(
            instrument=tick.instrument, price=tick.price,
            change=None if previous is None else tick.price - previous,
            last_tick_at=getattr(provider, 'last_tick_at', None),
            ticks_received=getattr(provider, 'ticks_received', 0)))
