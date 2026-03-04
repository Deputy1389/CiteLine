"""
API route: Exports
"""
from __future__ import annotations

from typing import Literal

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
    status: Literal["pending", "running", "success", "partial", "failed", "needs_review"]
    artifacts: list[ArtifactResponse]


def _normalize_run_status(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == "completed":
        return "success"
    if raw in {"pending", "running", "success", "partial", "failed", "needs_review"}:
        return raw
    return "failed"


@router.get("/matters/{matter_id}/exports/latest", response_model=ExportsResponse)
def get_latest_exports(
    matter_id: str,
    export_mode: Literal["INTERNAL", "MEDIATION"] = "INTERNAL",
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Get artifacts from the latest exportable run for a matter."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    runs = (
        db.query(Run)
        .filter(Run.matter_id == matter_id, Run.status.in_(["success", "partial", "needs_review", "completed"]))
        .order_by(Run.finished_at.desc())
        .all()
    )
    mode = str(export_mode or "").strip().upper()
    run = None
    for cand in runs:
        cfg = cand.config_json if isinstance(cand.config_json, dict) else {}
        cand_mode = str(cfg.get("export_mode") or "").strip().upper()
        if cand_mode == mode:
            run = cand
            break
    if not run:
        raise HTTPException(status_code=404, detail=f"No exportable runs found for mode={mode} on this matter")

    artifacts = db.query(Artifact).filter_by(run_id=run.id).all()
    mode_path = f"/exports/{mode.lower()}/"
    known_mode_paths = ("/exports/internal/", "/exports/mediation/")
    filtered = []
    for artifact in artifacts:
        artifact_type = str(artifact.artifact_type).lower()
        storage_uri = str(artifact.storage_uri or "").replace("\\", "/").lower()
        if artifact_type != "pdf":
            filtered.append(artifact)
            continue
        if mode_path in storage_uri:
            filtered.append(artifact)
            continue
        # Backward compatibility: keep legacy PDF paths that do not encode export mode.
        if not any(path in storage_uri for path in known_mode_paths):
            filtered.append(artifact)
    if not filtered:
        filtered = artifacts
    return ExportsResponse(
        run_id=run.id,
        status=_normalize_run_status(run.status),
        artifacts=[
            ArtifactResponse(
                artifact_type=a.artifact_type,
                storage_uri=a.storage_uri,
                sha256=a.sha256,
                bytes=a.bytes,
            )
            for a in filtered
        ],
    )
