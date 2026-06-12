from datetime import datetime, timezone

from backend.app.broker.zerodha_market_data import ZerodhaMarketDataClient


def test_zerodha_tick_is_normalized_to_internal_tick() -> None:
    client = ZerodhaMarketDataClient(token_to_instrument_id={1001: 7})
    timestamp = datetime(2026, 5, 17, 9, 15)

    tick = client.normalize_tick(
        {
            "instrument_token": 1001,
            "tradingsymbol": "NIFTY_TEST_CE",
            "last_price": 110.5,
            "exchange_timestamp": timestamp,
            "volume_traded": 1200,
        }
    )

    assert tick.instrument_id == 7
    assert tick.instrument_token == 1001
    assert tick.symbol == "NIFTY_TEST_CE"
    assert tick.last_price == 110.5
    assert tick.timestamp == datetime(2026, 5, 17, 3, 45, tzinfo=timezone.utc)
    assert tick.volume == 1200
