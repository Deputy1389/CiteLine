"""
API route: Runs
"""
from __future__ import annotations

import json
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.db.database import get_db
from packages.db.models import Matter, Run, SourceDocument

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


def _run_in_background(run_id: str) -> None:
    """Run the pipeline in a background thread."""
    from apps.worker.pipeline import run_pipeline
    run_pipeline(run_id)


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

    # Launch background thread
    t = threading.Thread(target=_run_in_background, args=(run_id,), daemon=True)
    t.start()

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
