from pydantic_settings import BaseSettings, SettingsConfigDict


class ZerodhaSettings(BaseSettings):
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""
    kite_redirect_url: str = "http://127.0.0.1:8000/zerodha/callback"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


zerodha_settings = ZerodhaSettings()
