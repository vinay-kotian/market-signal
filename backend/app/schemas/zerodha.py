from typing import Optional

from pydantic import BaseModel


class ZerodhaSessionRequest(BaseModel):
    request_token: str


class ZerodhaConfigRequest(BaseModel):
    api_key: str
    api_secret: Optional[str] = None
    redirect_url: str
