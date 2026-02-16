"""
API route: Documents (upload)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.db.database import get_db
from packages.db.models import Matter, SourceDocument
from packages.shared.storage import save_upload, sha256_bytes

router = APIRouter(tags=["documents"])


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
):
    """Upload a PDF document for a matter."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    if file.content_type and "pdf" not in file.content_type.lower():
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    file_hash = sha256_bytes(content)

    # Check for existing document with same hash
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

    # Save file to disk
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
def list_documents(matter_id: str, db: Session = Depends(get_db)):
    """List documents for a matter."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

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
