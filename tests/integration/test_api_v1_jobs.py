from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///C:/CiteLine/data/test_citeline_api_v1_jobs.db"
os.environ["DATA_DIR"] = "C:/CiteLine/data"
os.environ["API_V1_JOBS_ENABLED"] = "true"

from apps.api.main import app
from packages.db.database import engine, get_session
from packages.db.models import Artifact, Base, Run


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _create_firm_matter_with_document(client: TestClient) -> tuple[str, str]:
    firm_resp = client.post("/firms", json={"name": "API v1 Firm"})
    assert firm_resp.status_code == 201
    firm_id = firm_resp.json()["id"]

    matter_resp = client.post(f"/firms/{firm_id}/matters", json={"title": "API v1 Matter"})
    assert matter_resp.status_code == 201
    matter_id = matter_resp.json()["id"]

    files = {"file": ("packet.pdf", b"%PDF-1.4...", "application/pdf")}
    doc_resp = client.post(f"/matters/{matter_id}/documents", files=files)
    assert doc_resp.status_code == 201
    return firm_id, matter_id


def test_v1_jobs_create_get_cancel(client: TestClient):
    _, matter_id = _create_firm_matter_with_document(client)

    create_resp = client.post(
        "/api/citeline/v1/jobs",
        json={"matter_id": matter_id, "export_mode": "INTERNAL", "max_pages": 5},
    )
    assert create_resp.status_code == 202
    payload = create_resp.json()
    assert payload["status"] == "pending"
    job_id = payload["job_id"]

    get_resp = client.get(f"/v1/jobs/{job_id}")
    assert get_resp.status_code == 200
    job = get_resp.json()
    assert job["job_id"] == job_id
    assert job["matter_id"] == matter_id
    assert job["status"] == "pending"

    cancel_resp = client.post(f"/v1/jobs/{job_id}/cancel")
    assert cancel_resp.status_code == 202
    cancelled = cancel_resp.json()
    assert cancelled["status"] == "failed"
    assert cancelled["error_message"] == "Cancelled by user"


def test_v1_jobs_artifacts_list(client: TestClient):
    _, matter_id = _create_firm_matter_with_document(client)

    create_resp = client.post("/v1/jobs", json={"matter_id": matter_id})
    assert create_resp.status_code == 202
    job_id = create_resp.json()["job_id"]

    with get_session() as session:
        session.add(
            Artifact(
                run_id=job_id,
                artifact_type="evidence_graph",
                storage_uri=f"C:/CiteLine/data/runs/{job_id}/output/evidence_graph.json",
                sha256="a" * 64,
                bytes=1234,
            )
        )

    list_resp = client.get(f"/v1/jobs/{job_id}/artifacts")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload["job_id"] == job_id
    assert len(payload["artifacts"]) == 1
    artifact = payload["artifacts"][0]
    assert artifact["artifact_type"] == "evidence_graph"
    assert artifact["filename"] == "evidence_graph.json"


def test_v1_jobs_feature_flag_disabled_returns_404(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_V1_JOBS_ENABLED", "false")
    resp = client.get("/v1/jobs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Not found"


def test_v1_jobs_status_normalization_and_download_artifact(client: TestClient):
    _, matter_id = _create_firm_matter_with_document(client)
    create_resp = client.post("/v1/jobs", json={"matter_id": matter_id})
    assert create_resp.status_code == 202
    job_id = create_resp.json()["job_id"]

    with get_session() as session:
        run = session.query(Run).filter_by(id=job_id).first()
        assert run is not None
        run.status = "completed"

    status_resp = client.get(f"/v1/jobs/{job_id}")
    assert status_resp.status_code == 200
    payload = status_resp.json()
    assert payload["status"] == "success"

    artifact_dir = Path(os.environ["DATA_DIR"]) / "artifacts" / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "sample.txt"
    artifact_path.write_text("artifact-content", encoding="utf-8")

    download_resp = client.get(f"/v1/jobs/{job_id}/artifacts/{artifact_path.name}")
    assert download_resp.status_code == 200
    assert download_resp.content == b"artifact-content"


def test_v1_jobs_create_idempotency_reuses_existing_job(client: TestClient):
    _, matter_id = _create_firm_matter_with_document(client)
    headers = {"Idempotency-Key": "idem-create-1"}

    first = client.post(
        "/v1/jobs",
        json={"matter_id": matter_id, "max_pages": 5, "export_mode": "INTERNAL"},
        headers=headers,
    )
    assert first.status_code == 202
    first_job = first.json()

    second = client.post(
        "/v1/jobs",
        json={"matter_id": matter_id, "max_pages": 5, "export_mode": "INTERNAL"},
        headers=headers,
    )
    assert second.status_code == 202
    second_job = second.json()

    assert second_job["job_id"] == first_job["job_id"]
    assert second_job["matter_id"] == first_job["matter_id"]


def test_v1_jobs_create_idempotency_payload_mismatch_returns_409(client: TestClient):
    _, matter_id = _create_firm_matter_with_document(client)
    headers = {"Idempotency-Key": "idem-create-2"}

    first = client.post(
        "/v1/jobs",
        json={"matter_id": matter_id, "max_pages": 5, "export_mode": "INTERNAL"},
        headers=headers,
    )
    assert first.status_code == 202

    second = client.post(
        "/v1/jobs",
        json={"matter_id": matter_id, "max_pages": 10, "export_mode": "INTERNAL"},
        headers=headers,
    )
    assert second.status_code == 409
    assert "different request payload" in second.json()["detail"]
