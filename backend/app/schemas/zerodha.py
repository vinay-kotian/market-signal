from pydantic import BaseModel


class ZerodhaSessionRequest(BaseModel):
    request_token: str

