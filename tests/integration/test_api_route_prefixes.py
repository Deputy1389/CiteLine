from fastapi.testclient import TestClient

from apps.api.main import app


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
