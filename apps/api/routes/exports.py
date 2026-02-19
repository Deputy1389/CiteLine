"""
API route: Exports
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.db.database import get_db
from packages.db.models import Artifact, Matter, Run
from apps.api.authz import RequestIdentity, assert_firm_access, get_request_identity

router = APIRouter(tags=["exports"])


class ArtifactResponse(BaseModel):
    artifact_type: str
    storage_uri: str
    sha256: str
    bytes: int


class ExportsResponse(BaseModel):
    run_id: str
    status: str
    artifacts: list[ArtifactResponse]


@router.get("/matters/{matter_id}/exports/latest", response_model=ExportsResponse)
def get_latest_exports(
    matter_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Get artifacts from the latest completed run for a matter."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    run = (
        db.query(Run)
        .filter(Run.matter_id == matter_id, Run.status.in_(["success", "partial"]))
        .order_by(Run.finished_at.desc())
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="No completed runs found for this matter")

    artifacts = db.query(Artifact).filter_by(run_id=run.id).all()
    return ExportsResponse(
        run_id=run.id,
        status=run.status,
        artifacts=[
            ArtifactResponse(
                artifact_type=a.artifact_type,
                storage_uri=a.storage_uri,
                sha256=a.sha256,
                bytes=a.bytes,
            )
            for a in artifacts
        ],
    )
