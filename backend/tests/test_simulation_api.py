from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.market.tick_cache import tick_cache


def test_demo_simulation_runs_full_paper_flow() -> None:
    tick_cache._latest_ticks.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    response = client.post("/simulations/demo")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["instrument"]["symbol"] == "DEMO_NIFTY_CE"
    assert body["dashboard"]["counts"]["open_positions"] == 0
    assert body["dashboard"]["counts"]["recent_orders"] == 2
    assert body["dashboard"]["pnl"]["realized"] == 15
    assert any(
        result.get("checkpoint_name") == "L2"
        for item in body["timeline"]
        for result in item["results"]
        if isinstance(result, dict)
    )
    assert any(
        result.get("checkpoint_name") == "L3"
        for item in body["timeline"]
        for result in item["results"]
        if isinstance(result, dict)
    )
