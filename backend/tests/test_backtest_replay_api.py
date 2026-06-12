from fastapi.testclient import TestClient

from backend.app.main import app


def test_replay_api_runs_strategy_timeline() -> None:
    client = TestClient(app)

    response = client.post(
        "/backtests/replay",
        json={
            "instrument_id": 1,
            "instrument_token": 1001,
            "symbol": "NIFTY_TEST_CE",
            "trading_day": "2026-05-17",
            "trailing_gap": 5,
            "levels": [
                {"name": "L0", "price": 100, "role": "STOPLOSS"},
                {"name": "L1", "price": 110, "role": "ENTRY"},
                {"name": "L2", "price": 120, "role": "CHECKPOINT"},
            ],
            "ticks": [
                {"price": 108},
                {"price": 110},
                {"price": 120},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["timeline"]) == 3
    assert body["timeline"][1]["results"][0]["success"] is True
    assert body["timeline"][2]["position"]["trailing_stoploss_price"] == 115
    assert "L2" in body["timeline"][2]["position"]["reached_checkpoints"]

