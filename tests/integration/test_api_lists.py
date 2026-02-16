"""
Integration tests for API list endpoints.
"""
from __future__ import annotations

import os
from fastapi.testclient import TestClient
import pytest

# Setup test environment before imports
os.environ.setdefault("DATABASE_URL", "sqlite:///C:/CiteLine/data/test_citeline_api_lists.db")
os.environ.setdefault("DATA_DIR", "C:/CiteLine/data")

from packages.db.database import engine
from packages.db.models import Base, Run
from apps.api.main import app

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def client():
    return TestClient(app)

class TestApiLists:
    def test_list_endpoints(self, client):
        # 1. Create Firm
        resp = client.post("/firms", json={"name": "Test Firm A"})
        assert resp.status_code == 201
        firm_id = resp.json()["id"]

        # 2. List Firms
        resp = client.get("/firms")
        assert resp.status_code == 200
        firms = resp.json()
        assert len(firms) >= 1
        assert any(f["id"] == firm_id for f in firms)
        assert any(f["name"] == "Test Firm A" for f in firms)

        # 3. Get Specific Firm
        resp = client.get(f"/firms/{firm_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == firm_id

        # 4. Create Matters
        m1 = client.post(f"/firms/{firm_id}/matters", json={"title": "Matter 1"}).json()
        m2 = client.post(f"/firms/{firm_id}/matters", json={"title": "Matter 2"}).json()

        # 5. List Matters for Firm
        resp = client.get(f"/firms/{firm_id}/matters")
        assert resp.status_code == 200
        matters = resp.json()
        assert len(matters) == 2
        matter_ids = {m["id"] for m in matters}
        assert m1["id"] in matter_ids
        assert m2["id"] in matter_ids

        # 6. Get Specific Matter
        resp = client.get(f"/matters/{m1['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Matter 1"

        # 7. Upload Documents
        files = {"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")}
        d1 = client.post(f"/matters/{m1['id']}/documents", files=files).json()
        
        files2 = {"file": ("test2.pdf", b"%PDF-1.5... DIFFERENT CONTENT", "application/pdf")}
        d2 = client.post(f"/matters/{m1['id']}/documents", files=files2).json()

        # 8. List Documents
        resp = client.get(f"/matters/{m1['id']}/documents")
        assert resp.status_code == 200
        docs = resp.json()
        assert len(docs) == 2
        doc_filenames = {d["filename"] for d in docs}
        assert "test.pdf" in doc_filenames
        assert "test2.pdf" in doc_filenames

        import time
        # 9. Create Runs
        r1 = client.post(f"/matters/{m1['id']}/runs", json={"max_pages": 10}).json()
        time.sleep(1.1)  # Ensure distinct created_at for sorting
        r2 = client.post(f"/matters/{m1['id']}/runs", json={"max_pages": 20}).json()

        # 10. List Runs
        resp = client.get(f"/matters/{m1['id']}/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 2
        # Verify ordering (newest first)
        assert runs[0]["id"] == r2["id"]
        assert runs[1]["id"] == r1["id"]
        assert runs[0]["status"] == "pending"
