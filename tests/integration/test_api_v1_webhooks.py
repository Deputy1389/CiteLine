from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///C:/CiteLine/data/test_citeline_api_v1_webhooks.db"
os.environ["DATA_DIR"] = "C:/CiteLine/data"
os.environ["API_V1_WEBHOOKS_ENABLED"] = "true"

from apps.api.main import app
from packages.db.database import engine
from packages.db.models import Base


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _create_firm(client: TestClient) -> str:
    resp = client.post("/firms", json={"name": "Webhook Firm"})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_v1_webhooks_endpoint_lifecycle(client: TestClient):
    firm_id = _create_firm(client)

    create = client.post(
        "/v1/webhooks/endpoints",
        json={
            "firm_id": firm_id,
            "callback_url": "https://example.com/callback",
            "secret": "supersecretkey1",
            "description": "Partner callback",
        },
    )
    assert create.status_code == 201
    endpoint = create.json()
    endpoint_id = endpoint["endpoint_id"]
    assert endpoint["active"] is True
    assert endpoint["secret_last4"] == "key1"

    listed = client.get(f"/v1/webhooks/endpoints?firm_id={firm_id}")
    assert listed.status_code == 200
    payload = listed.json()
    assert len(payload["endpoints"]) == 1
    assert payload["endpoints"][0]["endpoint_id"] == endpoint_id

    fetched = client.get(f"/v1/webhooks/endpoints/{endpoint_id}")
    assert fetched.status_code == 200
    assert fetched.json()["callback_url"] == "https://example.com/callback"

    deleted = client.delete(f"/v1/webhooks/endpoints/{endpoint_id}")
    assert deleted.status_code == 200
    assert deleted.json()["active"] is False

    listed_active = client.get(f"/v1/webhooks/endpoints?firm_id={firm_id}")
    assert listed_active.status_code == 200
    assert listed_active.json()["endpoints"] == []

    listed_all = client.get(f"/v1/webhooks/endpoints?firm_id={firm_id}&active_only=false")
    assert listed_all.status_code == 200
    assert len(listed_all.json()["endpoints"]) == 1
    assert listed_all.json()["endpoints"][0]["active"] is False


def test_v1_webhooks_invalid_callback_url_rejected(client: TestClient):
    firm_id = _create_firm(client)
    resp = client.post(
        "/v1/webhooks/endpoints",
        json={
            "firm_id": firm_id,
            "callback_url": "ftp://example.com/callback",
            "secret": "supersecretkey1",
        },
    )
    assert resp.status_code == 400
    assert "callback_url" in resp.json()["detail"]


def test_v1_webhooks_feature_flag_disabled_returns_404(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_V1_WEBHOOKS_ENABLED", "false")
    resp = client.get("/v1/webhooks/endpoints?firm_id=does-not-matter")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Not found"
