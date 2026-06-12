from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Settings(BaseSettings):
    app_name: str = "Market Signal"
    database_url: str = "sqlite:///./market_signal.db"
    trading_mode: TradingMode = TradingMode.PAPER
    enable_live_trading: bool = False
    broker: str = "ZERODHA"
    square_off_time: str = "15:15"
    frontend_url: str = "http://127.0.0.1:3000"
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000,http://0.0.0.0:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
