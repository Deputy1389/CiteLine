from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///C:/CiteLine/data/test_citeline_api_v1_webhooks.db"
os.environ["DATA_DIR"] = "C:/CiteLine/data"
os.environ["API_V1_WEBHOOKS_ENABLED"] = "true"
os.environ["API_V1_JOBS_ENABLED"] = "true"
os.environ["API_V1_WEBHOOK_DELIVERY_ENABLED"] = "false"

from apps.api.main import app
from packages.db.database import engine, get_session
from packages.db.models import Base, WebhookEvent


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


def _create_matter_with_document(client: TestClient, firm_id: str) -> str:
    matter_resp = client.post(f"/firms/{firm_id}/matters", json={"title": "Webhook Matter"})
    assert matter_resp.status_code == 201
    matter_id = matter_resp.json()["id"]

    files = {"file": ("packet.pdf", b"%PDF-1.4...", "application/pdf")}
    doc_resp = client.post(f"/matters/{matter_id}/documents", files=files)
    assert doc_resp.status_code == 201
    return matter_id


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


def test_v1_jobs_create_emits_webhook_event_records(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_V1_WEBHOOK_DELIVERY_ENABLED", "false")
    firm_id = _create_firm(client)
    matter_id = _create_matter_with_document(client, firm_id)

    create_endpoint = client.post(
        "/v1/webhooks/endpoints",
        json={
            "firm_id": firm_id,
            "callback_url": "https://example.com/callback",
            "secret": "supersecretkey1",
        },
    )
    assert create_endpoint.status_code == 201

    create_job = client.post("/v1/jobs", json={"matter_id": matter_id})
    assert create_job.status_code == 202
    job_id = create_job.json()["job_id"]

    with get_session() as session:
        rows = session.query(WebhookEvent).all()
        assert len(rows) == 1
        event = rows[0]
        assert event.event_type == "job.pending"
        assert event.delivery_status == "pending"
        assert event.attempt_count == 0
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        assert payload.get("job_id") == job_id
        assert payload.get("matter_id") == matter_id


def test_v1_webhooks_replay_dispatches_with_signature(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_V1_WEBHOOK_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("API_V1_WEBHOOK_DELIVERY_ATTEMPTS", "1")
    firm_id = _create_firm(client)

    created = client.post(
        "/v1/webhooks/endpoints",
        json={
            "firm_id": firm_id,
            "callback_url": "https://example.com/callback",
            "secret": "supersecretkey2",
        },
    )
    assert created.status_code == 201
    endpoint_id = created.json()["endpoint_id"]

    with get_session() as session:
        event = WebhookEvent(
            endpoint_id=endpoint_id,
            event_type="job.pending",
            payload_json={"job_id": "job123"},
            delivery_status="pending",
            attempt_count=0,
        )
        session.add(event)
        session.flush()
        event_id = event.id

    captured: dict[str, str] = {}

    def _fake_post(url, data, headers, timeout):  # noqa: ANN001
        captured["url"] = url
        captured["signature"] = headers.get("X-Citeline-Signature", "")
        captured["event_type"] = headers.get("X-Citeline-Event-Type", "")
        class _Resp:
            status_code = 204
        return _Resp()

    monkeypatch.setattr("apps.api.routes.webhooks_v1.requests.post", _fake_post)

    replay = client.post(f"/v1/webhooks/events/{event_id}/replay")
    assert replay.status_code == 200
    payload = replay.json()
    assert payload["event_id"] == event_id
    assert payload["delivery_status"] == "delivered"
    assert payload["attempt_count"] == 1
    assert captured["url"] == "https://example.com/callback"
    assert captured["event_type"] == "job.pending"
    assert len(captured["signature"]) == 64
