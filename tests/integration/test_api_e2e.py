"""
Integration test: API end-to-end happy path.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Setup test environment before imports
os.environ.setdefault("DATABASE_URL", "sqlite:///C:/CiteLine/data/test_citeline_api.db")
os.environ.setdefault("DATA_DIR", "C:/CiteLine/data")

from packages.db.database import engine
from packages.db.models import Base
from apps.api.main import app

@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh tables for each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def client():
    return TestClient(app)

def _generate_fixture_pdf() -> bytes:
    from tests.fixtures.generate_fixture import create_synthetic_pdf
    return create_synthetic_pdf()

class TestApiE2E:
    def test_happy_path(self, client):
        """
        1. Create user/firm? No, just firm.
        2. Create matter
        3. Upload document
        4. Start run
        5. Poll status
        6. Get exports
        """
        # 1. Create Firm
        resp = client.post("/firms", json={"name": "Test Law Firm"})
        assert resp.status_code == 201
        firm_id = resp.json()["id"]

        # 2. Create Matter
        resp = client.post(f"/firms/{firm_id}/matters", json={
            "title": "Smith v. Doe",
            "timezone": "America/New_York",
        })
        assert resp.status_code == 201
        matter_id = resp.json()["id"]

        # 3. Upload Document
        pdf_bytes = _generate_fixture_pdf()
        files = {
            "file": ("medical_record.pdf", pdf_bytes, "application/pdf")
        }
        resp = client.post(f"/matters/{matter_id}/documents", files=files)
        assert resp.status_code == 201
        doc_data = resp.json()
        doc_id = doc_data["id"]
        assert doc_data["filename"] == "medical_record.pdf"

        # 4. Start Run
        resp = client.post(f"/matters/{matter_id}/runs", json={
            "max_pages": 100
        })
        assert resp.status_code == 202
        run_data = resp.json()
        run_id = run_data["id"]
        assert run_data["status"] == "pending"
        
        # Execute pipeline manually (simulating worker)
        from apps.worker.pipeline import run_pipeline
        run_pipeline(run_id)

        # 5. Poll Status (should be done)
        for _ in range(30):  # Wait up to 30s
            time.sleep(1)
            resp = client.get(f"/runs/{run_id}")
            assert resp.status_code == 200
            status = resp.json()["status"]
            if status in ("success", "partial", "failed"):
                break
        
        assert status in ("success", "partial"), f"Run failed: {resp.json().get('error_message')}"

        # 6. Get Exports
        resp = client.get(f"/matters/{matter_id}/exports/latest")
        assert resp.status_code == 200
        exports = resp.json()
        assert exports["run_id"] == run_id
        
        artifacts = exports["artifacts"]
        assert len(artifacts) >= 2
        types = {a["artifact_type"] for a in artifacts}
        assert "pdf" in types
        assert "csv" in types
        
        # Verify URIs exist
        for a in artifacts:
            assert Path(a["storage_uri"]).exists()

        # 7. Download Artifacts via API
        for artifact_type in ["pdf", "csv", "json"]:
            resp = client.get(f"/runs/{run_id}/artifacts/{artifact_type}")
            assert resp.status_code == 200, f"Failed to download {artifact_type}"
            assert len(resp.content) > 0
            assert resp.headers["content-type"] == "application/octet-stream"
