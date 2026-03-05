"""
API route: Runs
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.authz import RequestIdentity, assert_firm_access, get_request_identity
from packages.db.database import get_db
from packages.db.models import Artifact, Matter, Run, SourceDocument
from packages.shared.artifacts import artifact_extension, is_valid_artifact_type
from packages.shared.models import RunConfig

router = APIRouter(tags=["runs"])
_RUNCFG_DEFAULTS = RunConfig()


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


class CreateRunRequest(BaseModel):
    max_pages: int = _RUNCFG_DEFAULTS.max_pages
    include_billing_events_in_timeline: bool = False
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
    quality_mode: Literal["strict", "pilot"] = _RUNCFG_DEFAULTS.quality_mode
    export_mode: Literal["INTERNAL", "MEDIATION"] = "INTERNAL"


class RunResponse(BaseModel):
    id: str
    matter_id: str
    status: Literal["pending", "running", "success", "partial", "failed", "needs_review"]
    started_at: str | None
    heartbeat_at: str | None
    finished_at: str | None
    metrics: dict | None
    warnings: list | None
    error_message: str | None
    processing_seconds: float | None
    quality_gate_passed: bool | None = None
    quality_gate_score: int | None = None


@router.post("/matters/{matter_id}/runs", response_model=RunResponse, status_code=202)
def start_run(
    matter_id: str,
    req: CreateRunRequest = ...,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Start a new processing run for a matter."""
    matter = db.query(Matter).filter_by(id=matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    assert_firm_access(identity, matter.firm_id)

    # Pass 053: Enforce tier limits
    from packages.db.models import Firm
    from datetime import datetime, timedelta, timezone
    
    firm = db.query(Firm).filter_by(id=matter.firm_id).first()
    if firm:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        matter_count = db.query(Matter).filter(
            Matter.firm_id == matter.firm_id,
            Matter.created_at >= thirty_days_ago
        ).count()
        
        limit = 5 if firm.tier == "starter" else 20
        if firm.tier == "enterprise":
            limit = 1000000
            
        if matter_count > limit:
            raise HTTPException(
                status_code=402, 
                detail=f"Matter limit reached for {firm.tier} tier ({limit}/mo). Please upgrade your plan."
            )

    doc_count = db.query(SourceDocument).filter_by(matter_id=matter_id).count()
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
        "quality_mode": req.quality_mode,
        "export_mode": req.export_mode,
    }

    run = Run(
        matter_id=matter_id,
        status="pending",
        config_json=config,
    )
    db.add(run)
    db.flush()

    return RunResponse(
        id=run.id,
        matter_id=run.matter_id,
        status=_normalize_run_status(run.status),
        started_at=None,
        heartbeat_at=run.heartbeat_at.isoformat() if run.heartbeat_at else None,
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
        metrics = _coerce_json_value(r.metrics_json, dict)
        warnings = _coerce_json_value(r.warnings_json, list)

        response.append(
            RunResponse(
                id=r.id,
                matter_id=r.matter_id,
                status=_normalize_run_status(r.status),
                started_at=r.started_at.isoformat() if r.started_at else None,
                heartbeat_at=r.heartbeat_at.isoformat() if r.heartbeat_at else None,
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

    metrics = _coerce_json_value(run.metrics_json, dict)
    warnings = _coerce_json_value(run.warnings_json, list)

    return RunResponse(
        id=run.id,
        matter_id=run.matter_id,
        status=_normalize_run_status(run.status),
        started_at=run.started_at.isoformat() if run.started_at else None,
        heartbeat_at=run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        metrics=metrics,
        warnings=warnings,
        error_message=run.error_message,
        processing_seconds=run.processing_seconds,
    )


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Cancel a pending or running run."""
    run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    matter = db.query(Matter).filter_by(id=run.matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    if run.status not in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="Run is not active")

    run.status = "failed"
    run.finished_at = datetime.now(timezone.utc)
    run.error_message = "Cancelled by user"

    metrics = _coerce_json_value(run.metrics_json, dict)
    warnings = _coerce_json_value(run.warnings_json, list)

    return RunResponse(
        id=run.id,
        matter_id=run.matter_id,
        status=_normalize_run_status(run.status),
        started_at=run.started_at.isoformat() if run.started_at else None,
        heartbeat_at=run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        metrics=metrics,
        warnings=warnings,
        error_message=run.error_message,
        processing_seconds=run.processing_seconds,
    )


@router.post("/runs/{run_id}/force-fail", response_model=RunResponse)
def force_fail_run(
    run_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity | None = Depends(get_request_identity),
):
    """Force a run into failed state regardless of current status."""
    run = db.query(Run).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    matter = db.query(Matter).filter_by(id=run.matter_id).first()
    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")
    assert_firm_access(identity, matter.firm_id)

    run.status = "failed"
    run.finished_at = datetime.now(timezone.utc)
    run.error_message = "Force-failed by user"

    metrics = _coerce_json_value(run.metrics_json, dict)
    warnings = _coerce_json_value(run.warnings_json, list)

    return RunResponse(
        id=run.id,
        matter_id=run.matter_id,
        status=_normalize_run_status(run.status),
        started_at=run.started_at.isoformat() if run.started_at else None,
        heartbeat_at=run.heartbeat_at.isoformat() if run.heartbeat_at else None,
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
    export_mode: Literal["INTERNAL", "MEDIATION"] | None = None,
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
    if str(artifact_type).lower() == "pdf":
        if export_mode is None:
            raise HTTPException(status_code=422, detail="export_mode is required for PDF artifact download")
        run_mode = ""
        if isinstance(run.config_json, dict):
            run_mode = str(run.config_json.get("export_mode") or "").strip().upper()
        if run_mode and run_mode != str(export_mode).upper():
            raise HTTPException(status_code=409, detail=f"Run export mode is {run_mode}; requested {export_mode}")

    from pathlib import Path

    from packages.shared.storage import get_artifact_path

    # Extract filename from storage_uri and use get_artifact_path which downloads from Supabase
    filename = Path(artifact.storage_uri).name
    file_path_str = get_artifact_path(run_id, filename)
    if not file_path_str or not Path(file_path_str).exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")

    file_path = Path(file_path_str)
    ext = artifact_extension(artifact_type)

    return FileResponse(
        path=str(file_path),
        filename=f"run_{run_id}_{artifact_type}.{ext}",
        media_type="application/octet-stream",
    )


@router.get("/runs/{run_id}/artifacts/by-name/{filename}")
def download_artifact_by_name(
    run_id: str,
    filename: str,
    export_mode: Literal["INTERNAL", "MEDIATION"] | None = None,
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

    from packages.shared.storage import get_artifact_path

    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if safe_name.lower().endswith(".pdf"):
        if export_mode is None:
            raise HTTPException(status_code=422, detail="export_mode is required for PDF artifact download")
        run_mode = ""
        if isinstance(run.config_json, dict):
            run_mode = str(run.config_json.get("export_mode") or "").strip().upper()
        if run_mode and run_mode != str(export_mode).upper():
            raise HTTPException(status_code=409, detail=f"Run export mode is {run_mode}; requested {export_mode}")

    # Use get_artifact_path which downloads from Supabase if file not local
    file_path = get_artifact_path(run_id, safe_name)
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="application/octet-stream",
    )
