from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


PAYLOAD = {"instrument": "NIFTY", "price": 25000, "enabled": True}


def test_create_and_get_level(client):
    response = client.post("/levels", json=PAYLOAD)
    assert response.status_code == 201
    level = response.json()
    assert level.items() >= PAYLOAD.items()
    assert isinstance(level["id"], int)
    assert level["id"] > 0
    assert level["created_at"] == level["updated_at"]
    assert datetime.fromisoformat(level["created_at"].replace("Z", "+00:00")).tzinfo
    response = client.get(f"/levels/{level['id']}")
    assert response.status_code == 200
    assert response.json() == level


def test_list_levels(client):
    response = client.get("/levels")
    assert response.status_code == 200
    assert response.json() == []
    first = client.post("/levels", json=PAYLOAD).json()
    second = client.post("/levels", json={**PAYLOAD, "price": 25100}).json()
    assert client.get("/levels").json() == [first, second]


def test_update_level(client):
    original = client.post("/levels", json=PAYLOAD).json()
    changes = {"instrument": "BANKNIFTY", "price": 51000.5, "enabled": False}
    response = client.put(f"/levels/{original['id']}", json=changes)
    assert response.status_code == 200
    updated = response.json()
    assert updated.items() >= changes.items()
    assert updated["id"] == original["id"]
    assert updated["created_at"] == original["created_at"]
    assert updated["updated_at"] > original["updated_at"]
    assert client.get(f"/levels/{original['id']}").json() == updated


def test_delete_level(client):
    level = client.post("/levels", json=PAYLOAD).json()
    response = client.delete(f"/levels/{level['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/levels/{level['id']}").status_code == 404
    assert client.get("/levels").json() == []


@pytest.mark.parametrize("method", ["get", "put", "delete"])
@pytest.mark.parametrize("level_id", [999, 9223372036854775807])
def test_missing_level_id(client, method, level_id):
    kwargs = {"json": PAYLOAD} if method == "put" else {}
    response = client.request(method, f"/levels/{level_id}", **kwargs)
    assert response.status_code == 404
    assert response.json() == {"detail": "Level not found"}


@pytest.mark.parametrize("method", ["get", "put", "delete"])
@pytest.mark.parametrize("level_id", ["not-an-id", 0, -1, 9223372036854775808])
def test_invalid_level_id(client, method, level_id):
    kwargs = {"json": PAYLOAD} if method == "put" else {}
    assert client.request(method, f"/levels/{level_id}", **kwargs).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {**PAYLOAD, "instrument": "   "},
        {**PAYLOAD, "price": "invalid"},
        {**PAYLOAD, "price": "Infinity"},
        {"instrument": "NIFTY", "price": 25000},
        {**PAYLOAD, "id": 123},
    ],
)
def test_invalid_input_does_not_change_data(client, payload):
    original = client.post("/levels", json=PAYLOAD).json()
    assert client.post("/levels", json=payload).status_code == 422
    assert client.put(f"/levels/{original['id']}", json=payload).status_code == 422
    assert client.get("/levels").json() == [original]


def test_levels_persist_after_app_restart(tmp_path):
    database_path = tmp_path / "persistent.sqlite3"
    with TestClient(create_app(database_path)) as client:
        level = client.post("/levels", json=PAYLOAD).json()
    with TestClient(create_app(database_path)) as client:
        assert client.get(f"/levels/{level['id']}").json() == level
