from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///C:/CiteLine/data/test_citeline_direct_upload.db")
os.environ.setdefault("DATA_DIR", "C:/CiteLine/data")
os.environ.setdefault("UPLOAD_INTENT_SECRET", "test-upload-intent-secret-1234567890")

from apps.api.main import app
from apps.api.routes import documents as documents_route
from packages.db.database import engine, get_session_factory
from packages.db.models import Base, SourceDocument

SessionLocal = get_session_factory()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def _create_matter(client: TestClient) -> str:
    firm = client.post("/firms", json={"name": "Direct Upload Firm"}).json()
    matter = client.post(f"/firms/{firm['id']}/matters", json={"title": "Direct Upload Matter"}).json()
    return str(matter["id"])


def test_direct_upload_happy_path(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    matter_id = _create_matter(client)
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    signed_urls: list[tuple[str, str, bool]] = []
    deleted: list[tuple[str, str]] = []

    monkeypatch.setattr(documents_route.storage_lib, "direct_upload_supported", lambda: True)

    def fake_create_signed_upload_url(bucket: str, path: str, *, upsert: bool = False):
        signed_urls.append((bucket, path, upsert))
        return {
            "signed_url": f"https://storage.example.test/storage/v1/object/upload/sign/{bucket}/{path}?token=test-token",
            "token": "test-token",
            "path": path,
            "bucket": bucket,
        }

    monkeypatch.setattr(documents_route.storage_lib, "create_signed_upload_url", fake_create_signed_upload_url)
    monkeypatch.setattr(documents_route.storage_lib, "download_uploaded_object", lambda bucket, path: pdf_bytes)
    monkeypatch.setattr(documents_route.storage_lib, "delete_uploaded_object", lambda bucket, path: deleted.append((bucket, path)) or True)
    monkeypatch.setattr(documents_route.storage_lib, "delete_local_upload", lambda document_id: False)

    init_resp = client.post(
        f"/matters/{matter_id}/documents/upload-init",
        json={
            "filename": "packet.pdf",
            "byte_size": len(pdf_bytes),
            "content_type": "application/pdf",
        },
    )
    assert init_resp.status_code == 200
    init_body = init_resp.json()
    assert init_body["bucket"] == "documents"
    assert init_body["document_id"]
    assert init_body["object_path"] == f"{init_body['document_id']}.pdf"
    assert init_body["signed_url"].startswith("https://storage.example.test/")
    assert signed_urls == [("documents", init_body["object_path"], False)]

    complete_resp = client.post(
        f"/matters/{matter_id}/documents/upload-complete",
        json={"upload_intent": init_body["upload_intent"]},
    )
    assert complete_resp.status_code == 201
    doc = complete_resp.json()
    assert doc["id"] == init_body["document_id"]
    assert doc["matter_id"] == matter_id
    assert doc["filename"] == "packet.pdf"
    assert doc["bytes"] == len(pdf_bytes)
    assert deleted == []


def test_direct_upload_reuses_existing_doc_for_duplicate_content(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    matter_id = _create_matter(client)
    pdf_bytes = b"%PDF-1.4\nDUPLICATE\n%%EOF"
    deleted: list[tuple[str, str]] = []

    monkeypatch.setattr(documents_route.storage_lib, "direct_upload_supported", lambda: True)
    monkeypatch.setattr(
        documents_route.storage_lib,
        "create_signed_upload_url",
        lambda bucket, path, upsert=False: {
            "signed_url": f"https://storage.example.test/storage/v1/object/upload/sign/{bucket}/{path}?token=test-token",
            "token": "test-token",
            "path": path,
            "bucket": bucket,
        },
    )
    monkeypatch.setattr(documents_route.storage_lib, "download_uploaded_object", lambda bucket, path: pdf_bytes)
    monkeypatch.setattr(documents_route.storage_lib, "delete_uploaded_object", lambda bucket, path: deleted.append((bucket, path)) or True)
    monkeypatch.setattr(documents_route.storage_lib, "delete_local_upload", lambda document_id: False)

    first_init = client.post(
        f"/matters/{matter_id}/documents/upload-init",
        json={"filename": "one.pdf", "byte_size": len(pdf_bytes), "content_type": "application/pdf"},
    ).json()
    first_doc = client.post(
        f"/matters/{matter_id}/documents/upload-complete",
        json={"upload_intent": first_init["upload_intent"]},
    ).json()

    second_init = client.post(
        f"/matters/{matter_id}/documents/upload-init",
        json={"filename": "two.pdf", "byte_size": len(pdf_bytes), "content_type": "application/pdf"},
    ).json()
    second_resp = client.post(
        f"/matters/{matter_id}/documents/upload-complete",
        json={"upload_intent": second_init["upload_intent"]},
    )
    assert second_resp.status_code == 201
    second_doc = second_resp.json()
    assert second_doc["id"] == first_doc["id"]
    assert deleted == [("documents", second_init["object_path"])]


def test_direct_upload_rejects_non_pdf_content(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    matter_id = _create_matter(client)
    bad_bytes = b"not-a-pdf"
    deleted: list[tuple[str, str]] = []

    monkeypatch.setattr(documents_route.storage_lib, "direct_upload_supported", lambda: True)
    monkeypatch.setattr(
        documents_route.storage_lib,
        "create_signed_upload_url",
        lambda bucket, path, upsert=False: {
            "signed_url": f"https://storage.example.test/storage/v1/object/upload/sign/{bucket}/{path}?token=test-token",
            "token": "test-token",
            "path": path,
            "bucket": bucket,
        },
    )
    monkeypatch.setattr(documents_route.storage_lib, "download_uploaded_object", lambda bucket, path: bad_bytes)
    monkeypatch.setattr(documents_route.storage_lib, "delete_uploaded_object", lambda bucket, path: deleted.append((bucket, path)) or True)
    monkeypatch.setattr(documents_route.storage_lib, "delete_local_upload", lambda document_id: False)

    init_body = client.post(
        f"/matters/{matter_id}/documents/upload-init",
        json={"filename": "bad.pdf", "byte_size": len(bad_bytes), "content_type": "application/pdf"},
    ).json()
    complete_resp = client.post(
        f"/matters/{matter_id}/documents/upload-complete",
        json={"upload_intent": init_body["upload_intent"]},
    )
    assert complete_resp.status_code == 400
    assert "valid PDF signature" in complete_resp.text
    assert deleted == [("documents", init_body["object_path"])]


def test_sweep_orphaned_direct_uploads_deletes_only_stale_unregistered_objects(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    matter_id = _create_matter(client)
    stale_time = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    fresh_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    deleted: list[tuple[str, str]] = []
    local_deleted: list[str] = []

    # Registered document that should survive the sweep.
    with SessionLocal() as db:
        doc = SourceDocument(
            id="a" * 32,
            matter_id=matter_id,
            filename="registered.pdf",
            mime_type="application/pdf",
            storage_uri="C:/CiteLine/data/uploads/" + ("a" * 32) + ".pdf",
            sha256="b" * 64,
            bytes=123,
        )
        db.add(doc)
        db.commit()

    monkeypatch.setattr(documents_route.storage_lib, "direct_upload_supported", lambda: True)
    monkeypatch.setattr(
        documents_route.storage_lib,
        "list_objects",
        lambda bucket, **kwargs: [
            {"name": f"{'a'*32}.pdf", "updated_at": stale_time},
            {"name": f"{'c'*32}.pdf", "updated_at": stale_time},
            {"name": f"{'d'*32}.pdf", "updated_at": fresh_time},
            {"name": "misc-folder", "updated_at": stale_time},
        ],
    )
    monkeypatch.setattr(documents_route.storage_lib, "delete_uploaded_object", lambda bucket, path: deleted.append((bucket, path)) or True)
    monkeypatch.setattr(documents_route.storage_lib, "delete_local_upload", lambda document_id: local_deleted.append(document_id) or True)

    with SessionLocal() as db:
        result = documents_route.sweep_orphaned_direct_uploads(db)

    assert result["listed"] == 4
    assert result["deleted"] == 1
    assert ("documents", f"{'c'*32}.pdf") in deleted
    assert local_deleted == [("c" * 32)]
