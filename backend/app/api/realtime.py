from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.services.realtime import realtime_hub

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/prices")
async def price_websocket(websocket: WebSocket) -> None:
    await realtime_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        realtime_hub.disconnect(websocket)
