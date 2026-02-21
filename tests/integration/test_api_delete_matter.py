from fastapi.testclient import TestClient

from apps.api.main import app


def test_delete_matter_legacy_and_prefixed():
    client = TestClient(app)

    firm_resp = client.post("/firms", json={"name": "Delete Matter Firm"})
    assert firm_resp.status_code == 201
    firm_id = firm_resp.json()["id"]

    m1 = client.post(f"/firms/{firm_id}/matters", json={"title": "Matter 1"}).json()
    m2 = client.post(f"/firms/{firm_id}/matters", json={"title": "Matter 2"}).json()

    resp1 = client.delete(f"/matters/{m1['id']}")
    assert resp1.status_code == 204

    resp2 = client.delete(f"/api/citeline/matters/{m2['id']}")
    assert resp2.status_code == 204


def test_delete_matter_blocked_with_active_run():
    client = TestClient(app)

    firm_resp = client.post("/firms", json={"name": "Active Run Firm"})
    assert firm_resp.status_code == 201
    firm_id = firm_resp.json()["id"]

    matter = client.post(f"/firms/{firm_id}/matters", json={"title": "Active Matter"}).json()

    files = {"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")}
    client.post(f"/matters/{matter['id']}/documents", files=files)

    client.post(f"/matters/{matter['id']}/runs", json={"max_pages": 1})

    resp = client.delete(f"/matters/{matter['id']}")
    assert resp.status_code == 409
