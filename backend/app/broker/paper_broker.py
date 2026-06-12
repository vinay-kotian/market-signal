from backend.app.broker.broker_client import BrokerClient
from backend.app.dto.trading_dto import TradeAction


class PaperBrokerClient(BrokerClient):
    def place_order(self, action: TradeAction) -> str:
        return f"PAPER-{action.instrument_id}-{action.side.value}-{action.price}"

