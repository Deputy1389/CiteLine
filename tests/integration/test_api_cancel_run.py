from fastapi.testclient import TestClient

from apps.api.main import app


def test_cancel_run():
    client = TestClient(app)

    firm_resp = client.post("/firms", json={"name": "Cancel Run Firm"})
    assert firm_resp.status_code == 201
    firm_id = firm_resp.json()["id"]

    matter = client.post(f"/firms/{firm_id}/matters", json={"title": "Cancelable Matter"}).json()

    files = {"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")}
    client.post(f"/matters/{matter['id']}/documents", files=files)

    run = client.post(f"/matters/{matter['id']}/runs", json={"max_pages": 1}).json()

    resp = client.post(f"/runs/{run['id']}/cancel")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "failed"
    assert payload["error_message"] == "Cancelled by user"
