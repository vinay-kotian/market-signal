from datetime import datetime
from typing import Callable, Dict, List

from backend.app.broker.broker_client import MarketDataClient
from backend.app.core.timezone import IST, as_utc
from backend.app.db.broker_config import effective_zerodha_config
from backend.app.dto.trading_dto import Tick


class ZerodhaNotConfiguredError(RuntimeError):
    pass


class ZerodhaMarketDataClient(MarketDataClient):
    def __init__(self, token_to_instrument_id: Dict[int, int], access_token: str = "") -> None:
        self.token_to_instrument_id = token_to_instrument_id
        self.access_token = access_token
        self._ticker = None

    def subscribe(self, instrument_tokens: List[int]) -> None:
        config = effective_zerodha_config()
        access_token = self.access_token or config.kite_access_token
        if not config.kite_api_key or not access_token:
            raise ZerodhaNotConfiguredError("Kite API key and access token are required")

        try:
            from kiteconnect import KiteTicker
        except ImportError as exc:
            raise ZerodhaNotConfiguredError(
                "Install kiteconnect before enabling Zerodha websocket"
            ) from exc

        self._ticker = KiteTicker(
            config.kite_api_key,
            access_token,
        )
        self._ticker.on_connect = lambda ws, response: ws.subscribe(instrument_tokens)

    def update_subscriptions(self, token_to_instrument_id: Dict[int, int]) -> None:
        previous_tokens = set(self.token_to_instrument_id)
        next_tokens = set(token_to_instrument_id)
        self.token_to_instrument_id = token_to_instrument_id
        if not self._ticker:
            return
        added_tokens = sorted(next_tokens - previous_tokens)
        removed_tokens = sorted(previous_tokens - next_tokens)
        if added_tokens:
            self._ticker.subscribe(added_tokens)
        if removed_tokens:
            self._ticker.unsubscribe(removed_tokens)

    def start(self, instrument_tokens: List[int], on_tick: Callable[[Tick], None]) -> None:
        self.subscribe(instrument_tokens)

        def handle_ticks(ws, ticks):
            for raw_tick in ticks:
                on_tick(self.normalize_tick(raw_tick))

        self._ticker.on_ticks = handle_ticks
        self._ticker.connect(threaded=True)

    def normalize_tick(self, raw_tick: dict) -> Tick:
        token = int(raw_tick["instrument_token"])
        timestamp = raw_tick.get("exchange_timestamp") or raw_tick.get("timestamp")
        if timestamp is None:
            timestamp = datetime.utcnow()
        timestamp = as_utc(timestamp, naive_timezone=IST)
        return Tick(
            instrument_token=token,
            instrument_id=self.token_to_instrument_id[token],
            symbol=str(raw_tick.get("tradingsymbol", token)),
            last_price=float(raw_tick["last_price"]),
            timestamp=timestamp,
            volume=raw_tick.get("volume_traded"),
        )
