"""
API route: Runs
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.authz import RequestIdentity, assert_firm_access, get_request_identity
from packages.db.database import get_db
from packages.db.models import Artifact, Matter, Run, SourceDocument
from packages.shared.artifacts import artifact_extension, is_valid_artifact_type

router = APIRouter(tags=["runs"])


class CreateRunRequest(BaseModel):
    max_pages: int = 500
    include_billing_events_in_timeline: bool = False
    pt_mode: str = "aggregate"
    gap_threshold_days: int = 45
    event_confidence_min_export: int = 60
    low_confidence_event_behavior: str = "exclude_from_export"


class RunResponse(BaseModel):
    id: str
    matter_id: str
    status: str
    started_at: str | None
    finished_at: str | None
    metrics: dict | None
    warnings: list | None
    error_message: str | None
    processing_seconds: float | None


@router.post("/matters/{matter_id}/runs", response_model=RunResponse, status_code=202)
def start_run(
    matter_id: str,
    req: CreateRunRequest = CreateRunRequest(),
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Start a new processing run for a matter."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    assert_firm_access(identity, matter.firm_id)

    doc_count = db.query(SourceDocument).filter_by(matter_id=matter_id).count()
    if doc_count == 0:
        raise HTTPException(status_code=400, detail="No documents uploaded for this matter")

    config = {
        "max_pages": req.max_pages,
        "include_billing_events_in_timeline": req.include_billing_events_in_timeline,
        "pt_mode": req.pt_mode,
        "gap_threshold_days": req.gap_threshold_days,
        "event_confidence_min_export": req.event_confidence_min_export,
        "low_confidence_event_behavior": req.low_confidence_event_behavior,
    }

    run = Run(
        matter_id=matter_id,
        status="pending",
        config_json=json.dumps(config),
    )
    db.add(run)
    db.flush()

    return RunResponse(
        id=run.id,
        matter_id=run.matter_id,
        status=run.status,
        started_at=None,
        finished_at=None,
        metrics=None,
        warnings=None,
        error_message=None,
        processing_seconds=None,
    )


@router.get("/matters/{matter_id}/runs", response_model=list[RunResponse])
def list_runs(
    matter_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """List all processing runs for a matter."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    assert_firm_access(identity, matter.firm_id)

    runs = db.query(Run).filter_by(matter_id=matter_id).order_by(Run.created_at.desc()).all()

    response = []
    for r in runs:
        metrics = json.loads(r.metrics_json) if r.metrics_json else None
        warnings = json.loads(r.warnings_json) if r.warnings_json else None

        response.append(
            RunResponse(
                id=r.id,
                matter_id=r.matter_id,
                status=r.status,
                started_at=r.started_at.isoformat() if r.started_at else None,
                finished_at=r.finished_at.isoformat() if r.finished_at else None,
                metrics=metrics,
                warnings=warnings,
                error_message=r.error_message,
                processing_seconds=r.processing_seconds,
            )
        )
    return response


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Get run status and metrics."""
    run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    matter = db.query(Matter).filter_by(id=run.matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    metrics = json.loads(run.metrics_json) if run.metrics_json else None
    warnings = json.loads(run.warnings_json) if run.warnings_json else None

    return RunResponse(
        id=run.id,
        matter_id=run.matter_id,
        status=run.status,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        metrics=metrics,
        warnings=warnings,
        error_message=run.error_message,
        processing_seconds=run.processing_seconds,
    )


@router.get("/runs/{run_id}/artifacts/{artifact_type}")
def download_artifact(
    run_id: str,
    artifact_type: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Download a run artifact."""
    if not is_valid_artifact_type(artifact_type):
        raise HTTPException(status_code=400, detail="Invalid artifact type")

    run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    matter = db.query(Matter).filter_by(id=run.matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    artifact = db.query(Artifact).filter_by(run_id=run_id, artifact_type=artifact_type).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    from pathlib import Path

    from packages.shared.storage import DATA_DIR

    data_dir = DATA_DIR.resolve()
    file_path = Path(artifact.storage_uri).resolve()
    ext = artifact_extension(artifact_type)

    try:
        file_path.relative_to(data_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")

    return FileResponse(
        path=str(file_path),
        filename=f"run_{run_id}_{artifact_type}.{ext}",
        media_type="application/octet-stream",
    )


@router.get("/runs/{run_id}/artifacts/by-name/{filename}")
def download_artifact_by_name(
    run_id: str,
    filename: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Download a run artifact by exact filename (e.g., evidence_graph.json)."""
    run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    matter = db.query(Matter).filter_by(id=run.matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    from pathlib import Path

    from packages.shared.storage import DATA_DIR, get_artifact_dir

    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    data_dir = DATA_DIR.resolve()
    file_path = (get_artifact_dir(run_id) / safe_name).resolve()
    try:
        file_path.relative_to(data_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="application/octet-stream",
    )
