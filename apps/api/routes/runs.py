"""
API route: Runs
"""
from __future__ import annotations

import json
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.db.database import get_db
from packages.db.models import Artifact, Matter, Run, SourceDocument

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
):
    """Start a new processing run for a matter."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    # Check for source documents
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
    run_id = run.id

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


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, db: Session = Depends(get_db)):
    """Get run status and metrics."""
    run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

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
def download_artifact(run_id: str, artifact_type: str, db: Session = Depends(get_db)):
    """Download a run artifact."""
    valid_types = [
        "pdf", "csv", "json",
        "provider_directory_csv", "provider_directory_json",
        "missing_records_csv", "missing_records_json",
        "billing_lines_csv", "billing_lines_json",
        "specials_summary_csv", "specials_summary_json",
    ]
    if artifact_type not in valid_types:
        raise HTTPException(status_code=400, detail="Invalid artifact type")

    artifact = (
        db.query(Artifact)
        .filter_by(run_id=run_id, artifact_type=artifact_type)
        .first()
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
        
    # Security check: Ensure file is within valid data directory to prevent path traversal
    # usage of os.path.abspath and commonprefix is a robust way if strict pathlib isn't available,
    # but pathlib is better.
    from pathlib import Path
    import os
    
    data_dir = Path(os.environ.get("DATA_DIR", "data")).resolve()
    file_path = Path(artifact.storage_uri).resolve()
    
    if not str(file_path).startswith(str(data_dir)):
        # For security, standard is 404 to avoid leaking existence, or 403.
        # But if DB says it exists but path is weird, it's a server error or attack.
        # Let's log and return 404 for safety.
        # logger.warning(f"Path traversal attempt: {file_path} not in {data_dir}")
        raise HTTPException(status_code=404, detail="Artifact not found")

    if not file_path.exists():
         raise HTTPException(status_code=404, detail="Artifact file missing")

    return FileResponse(
        path=str(file_path),
        filename=f"run_{run_id}_{artifact_type}.{artifact_type}",
        media_type="application/octet-stream",
    )
