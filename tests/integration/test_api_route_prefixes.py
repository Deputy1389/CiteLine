import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///C:/CiteLine/data/test_citeline_api_route_prefixes.db")
os.environ.setdefault("DATA_DIR", "C:/CiteLine/data")

from apps.api.main import app
from packages.db.database import engine
from packages.db.models import Base


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_create_matter_legacy_path_not_404():
    client = TestClient(app)
    firm_resp = client.post("/firms", json={"name": "Prefix Test Firm"})
    assert firm_resp.status_code == 201
    firm_id = firm_resp.json()["id"]

    resp = client.post(f"/firms/{firm_id}/matters", json={"title": "Legacy Path Matter"})
    assert resp.status_code != 404


def test_create_matter_prefixed_path_not_404():
    client = TestClient(app)
    firm_resp = client.post("/api/citeline/firms", json={"name": "Prefixed Test Firm"})
    assert firm_resp.status_code == 201
    firm_id = firm_resp.json()["id"]

    resp = client.post(
        f"/api/citeline/firms/{firm_id}/matters",
        json={"title": "Prefixed Path Matter"},
    )
    assert resp.status_code != 404
