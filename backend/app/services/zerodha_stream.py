from datetime import date
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.broker.zerodha_market_data import (
    ZerodhaMarketDataClient,
    ZerodhaNotConfiguredError,
)
from backend.app.core.config import TradingMode, settings
from backend.app.db.broker_sessions import get_active_zerodha_session
from backend.app.db.session import SessionLocal
from backend.app.db.trading_state import (
    get_active_instrument_token_map,
    validate_active_level_sets,
)
from backend.app.dto.trading_dto import Tick
from backend.app.services.tick_processor import process_tick


class ZerodhaStreamService:
    def __init__(self) -> None:
        self.running = False
        self.instrument_tokens: List[int] = []
        self.last_error: Optional[str] = None
        self.processed_ticks = 0
        self.client = None
        self.client_factory = None

    def status(self) -> Dict[str, object]:
        return {
            "running": self.running,
            "instrument_tokens": self.instrument_tokens,
            "processed_ticks": self.processed_ticks,
            "last_error": self.last_error,
        }

    def start(
        self,
        db: Session,
        client_factory: Callable[[Dict[int, int], str], ZerodhaMarketDataClient] = ZerodhaMarketDataClient,
    ) -> Dict[str, object]:
        if self.running:
            return self.refresh_subscriptions(db)

        if settings.trading_mode != TradingMode.PAPER:
            raise ZerodhaNotConfiguredError("Zerodha stream is allowed only in PAPER mode")
        if settings.enable_live_trading:
            raise ZerodhaNotConfiguredError("Refusing stream start while live trading is enabled")

        trading_day = date.today()
        session = get_active_zerodha_session(db, trading_day)
        if not session:
            raise ZerodhaNotConfiguredError("No active Zerodha session for today")

        token_map = get_active_instrument_token_map(db, trading_day)
        if not token_map:
            raise ZerodhaNotConfiguredError("No active instruments with levels for today")
        level_errors = validate_active_level_sets(db, trading_day)
        if level_errors:
            raise ZerodhaNotConfiguredError("; ".join(level_errors))

        self.instrument_tokens = sorted(token_map.keys())
        self.last_error = None
        self.client_factory = client_factory
        self.client = client_factory(token_map, session.access_token)
        self.client.start(self.instrument_tokens, self._handle_tick)
        self.running = True
        return self.status()

    def refresh_subscriptions(self, db: Session) -> Dict[str, object]:
        if not self.running:
            return self.status()

        token_map = self._active_token_map(db)
        previous_tokens = set(self.instrument_tokens)
        next_tokens = set(token_map.keys())
        if self.client and hasattr(self.client, "update_subscriptions"):
            self.client.update_subscriptions(token_map)
        elif self.client and getattr(self.client, "_ticker", None):
            added_tokens = sorted(next_tokens - previous_tokens)
            removed_tokens = sorted(previous_tokens - next_tokens)
            if added_tokens:
                self.client._ticker.subscribe(added_tokens)
            if removed_tokens and hasattr(self.client._ticker, "unsubscribe"):
                self.client._ticker.unsubscribe(removed_tokens)
            if hasattr(self.client, "token_to_instrument_id"):
                self.client.token_to_instrument_id = token_map
        self.instrument_tokens = sorted(next_tokens)
        self.last_error = None
        status = self.status()
        status["subscription_refreshed"] = True
        status["added_tokens"] = sorted(next_tokens - previous_tokens)
        status["removed_tokens"] = sorted(previous_tokens - next_tokens)
        return status

    def _active_token_map(self, db: Session) -> Dict[int, int]:
        trading_day = date.today()
        token_map = get_active_instrument_token_map(db, trading_day)
        if not token_map:
            raise ZerodhaNotConfiguredError("No active instruments with levels for today")
        level_errors = validate_active_level_sets(db, trading_day)
        if level_errors:
            raise ZerodhaNotConfiguredError("; ".join(level_errors))
        return token_map

    def stop(self) -> Dict[str, object]:
        if self.client and getattr(self.client, "_ticker", None):
            close = getattr(self.client._ticker, "close", None)
            if close:
                close()
        self.running = False
        return self.status()

    def _handle_tick(self, tick: Tick) -> None:
        db = SessionLocal()
        try:
            process_tick(
                db=db,
                instrument_token=tick.instrument_token,
                last_price=tick.last_price,
                timestamp=tick.timestamp,
                volume=tick.volume,
            )
            self.processed_ticks += 1
        except Exception as exc:
            self.last_error = str(exc)
        finally:
            db.close()


zerodha_stream_service = ZerodhaStreamService()
