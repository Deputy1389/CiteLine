"""
API route: Documents (upload)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.authz import RequestIdentity, assert_firm_access, get_request_identity
from packages.db.database import get_db
from packages.db.models import Matter, SourceDocument
from packages.shared import storage as storage_lib

router = APIRouter(tags=["documents"])
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
UPLOAD_INTENT_TTL_SECONDS = int(os.getenv("UPLOAD_INTENT_TTL_SECONDS", "7200"))
ORPHAN_SWEEP_ENABLED = os.getenv("UPLOAD_ORPHAN_SWEEP_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
ORPHAN_SWEEP_COOLDOWN_SECONDS = int(os.getenv("UPLOAD_ORPHAN_SWEEP_COOLDOWN_SECONDS", "900"))
ORPHAN_SWEEP_AGE_SECONDS = int(os.getenv("UPLOAD_ORPHAN_SWEEP_AGE_SECONDS", "10800"))
ORPHAN_SWEEP_LIMIT = int(os.getenv("UPLOAD_ORPHAN_SWEEP_LIMIT", "50"))
_LAST_ORPHAN_SWEEP_TS = 0.0
_DIRECT_UPLOAD_OBJECT_RE = re.compile(r"^(?P<document_id>[0-9a-f]{32})\.pdf$", re.I)


def _intent_secret() -> str:
    secret = (
        os.getenv("UPLOAD_INTENT_SECRET", "").strip()
        or os.getenv("API_INTERNAL_JWT_SECRET", "").strip()
        or os.getenv("API_INTERNAL_TOKEN", "").strip()
    )
    if len(secret) < 24:
        raise HTTPException(status_code=500, detail="Upload intent signing secret is not configured")
    return secret


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _sign_upload_intent(payload: dict[str, object]) -> str:
    encoded = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(_intent_secret().encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).digest()
    return f"{encoded}.{_b64url_encode(signature)}"


def _verify_upload_intent(token: str) -> dict[str, object]:
    try:
        encoded, sig = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid upload intent token") from exc

    expected_sig = hmac.new(_intent_secret().encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).digest()
    try:
        got_sig = _b64url_decode(sig)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid upload intent signature") from exc
    if not hmac.compare_digest(expected_sig, got_sig):
        raise HTTPException(status_code=403, detail="Upload intent signature mismatch")

    try:
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid upload intent payload") from exc

    exp = payload.get("exp")
    if not isinstance(exp, int) or int(time.time()) > exp:
        raise HTTPException(status_code=403, detail="Upload intent expired")
    return payload


class DocumentResponse(BaseModel):
    id: str
    matter_id: str
    filename: str
    mime_type: str
    sha256: str
    bytes: int
    storage_uri: str
    uploaded_at: str


class DirectUploadInitRequest(BaseModel):
    filename: str
    byte_size: int
    content_type: str = "application/pdf"


class DirectUploadInitResponse(BaseModel):
    document_id: str
    bucket: str
    object_path: str
    signed_url: str
    upload_intent: str
    max_upload_bytes: int
    expires_in_seconds: int


class DirectUploadCompleteRequest(BaseModel):
    upload_intent: str


def _validate_pdf_upload_request(filename: str, content_type: str, byte_size: int) -> None:
    if not filename.strip():
        raise HTTPException(status_code=400, detail="Filename is required")
    if content_type and "pdf" not in content_type.lower():
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    if byte_size <= 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if byte_size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds configured size limit")


def _cleanup_direct_upload_object(document_id: str, object_path: str) -> None:
    """Best-effort cleanup for rejected direct-upload objects."""
    try:
        storage_lib.delete_uploaded_object(storage_lib.DOCUMENTS_BUCKET, object_path)
    except Exception:
        pass
    try:
        storage_lib.delete_local_upload(document_id)
    except Exception:
        pass


def _reject_direct_upload(document_id: str, object_path: str, *, status_code: int, detail: str) -> None:
    _cleanup_direct_upload_object(document_id, object_path)
    raise HTTPException(status_code=status_code, detail=detail)


def _parse_storage_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def sweep_orphaned_direct_uploads(db: Session) -> dict[str, int]:
    """Best-effort bounded sweep for direct-upload objects with no SourceDocument row."""
    if not ORPHAN_SWEEP_ENABLED or not storage_lib.direct_upload_supported():
        return {"listed": 0, "deleted": 0, "skipped": 0}

    listed = storage_lib.list_objects(
        storage_lib.DOCUMENTS_BUCKET,
        limit=ORPHAN_SWEEP_LIMIT,
        sort_column="updated_at",
        sort_order="asc",
    )
    now = datetime.now(timezone.utc)
    deleted = 0
    skipped = 0

    for item in listed:
        name = str(item.get("name") or "").strip()
        match = _DIRECT_UPLOAD_OBJECT_RE.match(name)
        if not match:
            skipped += 1
            continue

        updated_at = _parse_storage_timestamp(item.get("updated_at") or item.get("created_at"))
        if updated_at is None:
            skipped += 1
            continue
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age_seconds = (now - updated_at).total_seconds()
        if age_seconds < ORPHAN_SWEEP_AGE_SECONDS:
            skipped += 1
            continue

        document_id = match.group("document_id").lower()
        exists = db.query(SourceDocument.id).filter_by(id=document_id).first()
        if exists:
            skipped += 1
            continue

        if storage_lib.delete_uploaded_object(storage_lib.DOCUMENTS_BUCKET, name):
            storage_lib.delete_local_upload(document_id)
            deleted += 1
        else:
            skipped += 1

    return {"listed": len(listed), "deleted": deleted, "skipped": skipped}


def maybe_sweep_orphaned_direct_uploads(db: Session) -> None:
    global _LAST_ORPHAN_SWEEP_TS
    if not ORPHAN_SWEEP_ENABLED:
        return
    now = time.time()
    if _LAST_ORPHAN_SWEEP_TS and (now - _LAST_ORPHAN_SWEEP_TS) < ORPHAN_SWEEP_COOLDOWN_SECONDS:
        return
    _LAST_ORPHAN_SWEEP_TS = now
    try:
        result = sweep_orphaned_direct_uploads(db)
        if result.get("deleted"):
            # Keep logging low-signal unless the sweep actually did work.
            pass
    except Exception:
        # Upload-init must not fail because the orphan sweep had an issue.
        return


def _build_document_response(doc: SourceDocument) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        matter_id=doc.matter_id,
        filename=doc.filename,
        mime_type=doc.mime_type,
        sha256=doc.sha256,
        bytes=doc.bytes,
        storage_uri=doc.storage_uri or "",
        uploaded_at=doc.uploaded_at.isoformat(),
    )


def _resolve_matter_for_upload(
    matter_id: str,
    db: Session,
    identity: RequestIdentity | None,
) -> Matter:
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)
    return matter


@router.post(
    "/matters/{matter_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
)
async def upload_document(
    matter_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Upload a PDF document for a matter."""
    _resolve_matter_for_upload(matter_id, db, identity)

    if file.content_type and "pdf" not in file.content_type.lower():
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds configured size limit")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF signature")

    file_hash = storage_lib.sha256_bytes(content)

    existing = db.query(SourceDocument).filter_by(
        matter_id=matter_id, sha256=file_hash
    ).first()
    if existing:
        return _build_document_response(existing)

    doc = SourceDocument(
        matter_id=matter_id,
        filename=file.filename or "upload.pdf",
        mime_type="application/pdf",
        sha256=file_hash,
        bytes=len(content),
    )
    db.add(doc)
    db.flush()

    path = storage_lib.save_upload(doc.id, content)
    doc.storage_uri = str(path)
    db.flush()

    return _build_document_response(doc)


@router.post(
    "/matters/{matter_id}/documents/upload-init",
    response_model=DirectUploadInitResponse,
)
def init_direct_upload(
    matter_id: str,
    request: DirectUploadInitRequest,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Create a signed direct-upload target for a PDF document."""
    _resolve_matter_for_upload(matter_id, db, identity)
    _validate_pdf_upload_request(request.filename, request.content_type, request.byte_size)
    maybe_sweep_orphaned_direct_uploads(db)

    if not storage_lib.direct_upload_supported():
        raise HTTPException(status_code=501, detail="Direct upload is not configured")

    document_id = uuid.uuid4().hex
    object_path = storage_lib.document_storage_path(document_id)
    try:
        signed = storage_lib.create_signed_upload_url(storage_lib.DOCUMENTS_BUCKET, object_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    now = int(time.time())
    upload_intent = _sign_upload_intent(
        {
            "typ": "direct_upload_intent",
            "matter_id": matter_id,
            "document_id": document_id,
            "object_path": object_path,
            "filename": request.filename,
            "content_type": request.content_type,
            "byte_size": request.byte_size,
            "iat": now,
            "exp": now + UPLOAD_INTENT_TTL_SECONDS,
        }
    )
    return DirectUploadInitResponse(
        document_id=document_id,
        bucket=storage_lib.DOCUMENTS_BUCKET,
        object_path=object_path,
        signed_url=signed["signed_url"],
        upload_intent=upload_intent,
        max_upload_bytes=MAX_UPLOAD_BYTES,
        expires_in_seconds=UPLOAD_INTENT_TTL_SECONDS,
    )


@router.post(
    "/matters/{matter_id}/documents/upload-complete",
    response_model=DocumentResponse,
    status_code=201,
)
def complete_direct_upload(
    matter_id: str,
    request: DirectUploadCompleteRequest,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Validate a direct-uploaded object and register the source document."""
    _resolve_matter_for_upload(matter_id, db, identity)
    payload = _verify_upload_intent(request.upload_intent)

    if payload.get("typ") != "direct_upload_intent":
        raise HTTPException(status_code=400, detail="Invalid upload intent type")
    if payload.get("matter_id") != matter_id:
        raise HTTPException(status_code=403, detail="Upload intent does not match matter")

    document_id = str(payload.get("document_id") or "").strip()
    object_path = str(payload.get("object_path") or "").strip()
    filename = str(payload.get("filename") or "upload.pdf").strip() or "upload.pdf"
    content_type = str(payload.get("content_type") or "application/pdf").strip() or "application/pdf"
    declared_bytes = int(payload.get("byte_size") or 0)
    if object_path != storage_lib.document_storage_path(document_id):
        _reject_direct_upload(document_id, object_path, status_code=400, detail="Upload intent object path mismatch")

    _validate_pdf_upload_request(filename, content_type, declared_bytes)

    content = storage_lib.download_uploaded_object(storage_lib.DOCUMENTS_BUCKET, object_path)
    if content is None:
        raise HTTPException(status_code=404, detail="Uploaded object not found")
    if len(content) == 0:
        _reject_direct_upload(document_id, object_path, status_code=400, detail="Uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        _reject_direct_upload(document_id, object_path, status_code=413, detail="Upload exceeds configured size limit")
    if declared_bytes and len(content) != declared_bytes:
        _reject_direct_upload(document_id, object_path, status_code=400, detail="Uploaded file size does not match upload intent")
    if not content.startswith(b"%PDF-"):
        _reject_direct_upload(document_id, object_path, status_code=400, detail="Uploaded file is not a valid PDF signature")

    file_hash = storage_lib.sha256_bytes(content)
    existing = db.query(SourceDocument).filter_by(matter_id=matter_id, sha256=file_hash).first()
    if existing:
        _cleanup_direct_upload_object(document_id, object_path)
        return _build_document_response(existing)

    path = storage_lib.save_upload(document_id, content, mirror_remote=False)
    try:
        doc = SourceDocument(
            id=document_id,
            matter_id=matter_id,
            filename=filename,
            mime_type="application/pdf",
            sha256=file_hash,
            bytes=len(content),
            storage_uri=str(path),
        )
        db.add(doc)
        db.flush()
    except Exception:
        _cleanup_direct_upload_object(document_id, object_path)
        raise
    return _build_document_response(doc)


@router.get(
    "/matters/{matter_id}/documents",
    response_model=list[DocumentResponse],
)
def list_documents(
    matter_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """List documents for a matter."""
    _resolve_matter_for_upload(matter_id, db, identity)

    docs = db.query(SourceDocument).filter_by(matter_id=matter_id).all()
    return [_build_document_response(d) for d in docs]


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Download original uploaded source PDF."""
    doc = db.query(SourceDocument).filter_by(id=document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    matter = db.query(Matter).filter_by(id=doc.matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    if not doc.storage_uri:
        raise HTTPException(status_code=404, detail="Document file missing: no storage_uri")

    # Use get_upload_path which downloads from Supabase if file not local
    file_path = storage_lib.get_upload_path(document_id)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Document file missing")

    return FileResponse(
        path=file_path,
        filename=doc.filename or f"{document_id}.pdf",
        media_type="application/pdf",
    )
