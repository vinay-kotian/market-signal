from datetime import date
from typing import Any, Dict, Optional

from backend.app.broker.zerodha_market_data import ZerodhaNotConfiguredError
from backend.app.db.broker_config import EffectiveZerodhaConfig, effective_zerodha_config


class ZerodhaSessionClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        config: Optional[EffectiveZerodhaConfig] = None,
    ) -> None:
        self.access_token = access_token
        self.config = config or effective_zerodha_config()

    def _client(self):
        if not self.config.kite_api_key:
            raise ZerodhaNotConfiguredError("KITE_API_KEY is required")

        try:
            from kiteconnect import KiteConnect
        except ImportError as exc:
            raise ZerodhaNotConfiguredError("Install kiteconnect to use Zerodha login") from exc

        client = KiteConnect(api_key=self.config.kite_api_key)
        token = self.access_token or self.config.kite_access_token
        if token:
            client.set_access_token(token)
        return client

    def status(self, active_token: Optional[str] = None) -> Dict[str, bool]:
        has_access_token = bool(active_token or self.config.kite_access_token)
        return {
            "api_key_configured": bool(self.config.kite_api_key),
            "api_secret_configured": bool(self.config.kite_api_secret),
            "access_token_configured": has_access_token,
            "db_session_active": bool(active_token),
            "ready_for_login": bool(self.config.kite_api_key),
            "ready_for_websocket": bool(
                self.config.kite_api_key and has_access_token
            ),
            "config_source": self.config.source,
        }

    def login_url(self) -> str:
        return str(self._client().login_url())

    def generate_session(self, request_token: str) -> Dict[str, Any]:
        if not self.config.kite_api_secret:
            raise ZerodhaNotConfiguredError("KITE_API_SECRET is required")
        try:
            return dict(
                self._client().generate_session(
                    request_token=request_token,
                    api_secret=self.config.kite_api_secret,
                )
            )
        except Exception as exc:
            raise ZerodhaSessionError(str(exc)) from exc

    @staticmethod
    def trading_day() -> date:
        return date.today()


class ZerodhaSessionError(RuntimeError):
    pass
