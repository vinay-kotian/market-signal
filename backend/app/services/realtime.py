import asyncio
from typing import Optional, Set

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class RealtimeHub:
    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._loop = asyncio.get_running_loop()
        self._connections.add(websocket)
        await websocket.send_json({"type": "connected"})

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    def publish(self, message: dict) -> None:
        if not self._connections or self._loop is None:
            return
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._broadcast(message))
        )

    async def _broadcast(self, message: dict) -> None:
        stale_connections = []
        for websocket in list(self._connections):
            if websocket.client_state != WebSocketState.CONNECTED:
                stale_connections.append(websocket)
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                stale_connections.append(websocket)
        for websocket in stale_connections:
            self.disconnect(websocket)


realtime_hub = RealtimeHub()
