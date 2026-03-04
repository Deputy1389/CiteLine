"""
API route: Versioned jobs facade (/v1/jobs)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.authz import RequestIdentity, assert_firm_access, get_request_identity
from packages.db.database import get_db
from packages.db.models import Artifact, Matter, Run, SourceDocument
from packages.shared.models import RunConfig

router = APIRouter(prefix="/v1", tags=["jobs-v1"])
_RUNCFG_DEFAULTS = RunConfig()


def _v1_jobs_enabled() -> bool:
    raw = os.getenv("API_V1_JOBS_ENABLED", "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _assert_v1_jobs_enabled() -> None:
    if not _v1_jobs_enabled():
        raise HTTPException(status_code=404, detail="Not found")


def _normalize_run_status(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == "completed":
        return "success"
    if raw in {"pending", "running", "success", "partial", "failed", "needs_review"}:
        return raw
    return "failed"


def _coerce_json_value(value, expected: type):
    if value is None:
        return None
    return value if isinstance(value, expected) else None


class JobCreateRequest(BaseModel):
    matter_id: str
    max_pages: int = _RUNCFG_DEFAULTS.max_pages
    pt_mode: str = str(_RUNCFG_DEFAULTS.pt_mode)
    pt_aggregate_window_days: int = _RUNCFG_DEFAULTS.pt_aggregate_window_days
    gap_threshold_days: int = _RUNCFG_DEFAULTS.gap_threshold_days
    event_confidence_min_export: int = _RUNCFG_DEFAULTS.event_confidence_min_export
    low_confidence_event_behavior: str = str(_RUNCFG_DEFAULTS.low_confidence_event_behavior)
    enable_llm_reasoning: bool = _RUNCFG_DEFAULTS.enable_llm_reasoning
    gemini_model: str = _RUNCFG_DEFAULTS.gemini_model
    llm_reasoning_min_confidence: int = _RUNCFG_DEFAULTS.llm_reasoning_min_confidence
    narrative_min_confidence: int = _RUNCFG_DEFAULTS.narrative_min_confidence
    chronology_min_score: int = _RUNCFG_DEFAULTS.chronology_min_score
    export_mode: Literal["INTERNAL", "MEDIATION"] = "INTERNAL"


class JobAcceptedResponse(BaseModel):
    job_id: str
    matter_id: str
    status: Literal["pending", "running", "success", "partial", "failed", "needs_review"]
    created_at: str | None


class JobStatusResponse(BaseModel):
    job_id: str
    matter_id: str
    status: Literal["pending", "running", "success", "partial", "failed", "needs_review"]
    created_at: str | None
    started_at: str | None
    heartbeat_at: str | None
    finished_at: str | None
    metrics: dict | None
    warnings: list | None
    error_message: str | None
    processing_seconds: float | None


class JobArtifactResponse(BaseModel):
    artifact_id: str
    artifact_type: str
    filename: str
    storage_uri: str
    sha256: str
    bytes: int


class JobArtifactsListResponse(BaseModel):
    job_id: str
    artifacts: list[JobArtifactResponse]


def _assert_job_access(run: Run, db: Session, identity: RequestIdentity | None) -> None:
    matter = db.query(Matter).filter_by(id=run.matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)


def _to_job_status(run: Run) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=run.id,
        matter_id=run.matter_id,
        status=_normalize_run_status(run.status),
        created_at=run.created_at.isoformat() if run.created_at else None,
        started_at=run.started_at.isoformat() if run.started_at else None,
        heartbeat_at=run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        metrics=_coerce_json_value(run.metrics_json, dict),
        warnings=_coerce_json_value(run.warnings_json, list),
        error_message=run.error_message,
        processing_seconds=run.processing_seconds,
    )


@router.post("/jobs", response_model=JobAcceptedResponse, status_code=202)
def create_job(
    req: JobCreateRequest,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    _assert_v1_jobs_enabled()

    matter = db.query(Matter).filter_by(id=req.matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    doc_count = db.query(SourceDocument).filter_by(matter_id=req.matter_id).count()
    if doc_count == 0:
        raise HTTPException(status_code=400, detail="No documents uploaded for this matter")

    config = {
        "max_pages": req.max_pages,
        "pt_mode": req.pt_mode,
        "pt_aggregate_window_days": req.pt_aggregate_window_days,
        "gap_threshold_days": req.gap_threshold_days,
        "event_confidence_min_export": req.event_confidence_min_export,
        "low_confidence_event_behavior": req.low_confidence_event_behavior,
        "enable_llm_reasoning": req.enable_llm_reasoning,
        "gemini_model": req.gemini_model,
        "llm_reasoning_min_confidence": req.llm_reasoning_min_confidence,
        "narrative_min_confidence": req.narrative_min_confidence,
        "chronology_min_score": req.chronology_min_score,
        "export_mode": req.export_mode,
    }

    run = Run(
        matter_id=req.matter_id,
        status="pending",
        config_json=config,
    )
    db.add(run)
    db.flush()

    return JobAcceptedResponse(
        job_id=run.id,
        matter_id=run.matter_id,
        status=_normalize_run_status(run.status),
        created_at=run.created_at.isoformat() if run.created_at else None,
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    _assert_v1_jobs_enabled()

    run = db.query(Run).filter_by(id=job_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Job not found")

    _assert_job_access(run, db, identity)
    return _to_job_status(run)


@router.get("/jobs/{job_id}/artifacts", response_model=JobArtifactsListResponse)
def list_job_artifacts(
    job_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    _assert_v1_jobs_enabled()

    run = db.query(Run).filter_by(id=job_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Job not found")

    _assert_job_access(run, db, identity)

    artifacts = (
        db.query(Artifact)
        .filter_by(run_id=job_id)
        .order_by(Artifact.id.asc())
        .all()
    )
    return JobArtifactsListResponse(
        job_id=job_id,
        artifacts=[
            JobArtifactResponse(
                artifact_id=a.id,
                artifact_type=a.artifact_type,
                filename=Path(a.storage_uri).name,
                storage_uri=a.storage_uri,
                sha256=a.sha256,
                bytes=a.bytes,
            )
            for a in artifacts
        ],
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse, status_code=202)
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    _assert_v1_jobs_enabled()

    run = db.query(Run).filter_by(id=job_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Job not found")

    _assert_job_access(run, db, identity)

    if run.status not in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="Job is not active")

    run.status = "failed"
    run.finished_at = datetime.now(timezone.utc)
    run.error_message = "Cancelled by user"

    return _to_job_status(run)
