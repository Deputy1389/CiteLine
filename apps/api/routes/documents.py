"""
API route: Documents (upload)
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.authz import RequestIdentity, assert_firm_access, get_request_identity
from packages.db.database import get_db
from packages.db.models import Matter, SourceDocument
from packages.shared.storage import save_upload, sha256_bytes

router = APIRouter(tags=["documents"])
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))


class DocumentResponse(BaseModel):
    id: str
    matter_id: str
    filename: str
    mime_type: str
    sha256: str
    bytes: int
    storage_uri: str
    uploaded_at: str


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
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    assert_firm_access(identity, matter.firm_id)

    if file.content_type and "pdf" not in file.content_type.lower():
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds configured size limit")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF signature")

    file_hash = sha256_bytes(content)

    existing = db.query(SourceDocument).filter_by(
        matter_id=matter_id, sha256=file_hash
    ).first()
    if existing:
        return DocumentResponse(
            id=existing.id,
            matter_id=existing.matter_id,
            filename=existing.filename,
            mime_type=existing.mime_type,
            sha256=existing.sha256,
            bytes=existing.bytes,
            storage_uri=existing.storage_uri or "",
            uploaded_at=existing.uploaded_at.isoformat(),
        )

    doc = SourceDocument(
        matter_id=matter_id,
        filename=file.filename or "upload.pdf",
        mime_type="application/pdf",
        sha256=file_hash,
        bytes=len(content),
    )
    db.add(doc)
    db.flush()

    path = save_upload(doc.id, content)
    doc.storage_uri = str(path)
    db.flush()

    return DocumentResponse(
        id=doc.id,
        matter_id=doc.matter_id,
        filename=doc.filename,
        mime_type=doc.mime_type,
        sha256=doc.sha256,
        bytes=doc.bytes,
        storage_uri=doc.storage_uri,
        uploaded_at=doc.uploaded_at.isoformat(),
    )


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
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    assert_firm_access(identity, matter.firm_id)

    docs = db.query(SourceDocument).filter_by(matter_id=matter_id).all()
    return [
        DocumentResponse(
            id=d.id,
            matter_id=d.matter_id,
            filename=d.filename,
            mime_type=d.mime_type,
            sha256=d.sha256,
            bytes=d.bytes,
            storage_uri=d.storage_uri or "",
            uploaded_at=d.uploaded_at.isoformat(),
        )
        for d in docs
    ]


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

    # Normalize path (handle Windows forward/backslash issues)
    file_path = os.path.normpath(doc.storage_uri)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Document file missing: {file_path} not found on disk")

    return FileResponse(
        path=file_path,
        filename=doc.filename or f"{document_id}.pdf",
        media_type="application/pdf",
    )
