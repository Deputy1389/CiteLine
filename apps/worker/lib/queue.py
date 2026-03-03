"""
apps/worker/lib/queue.py — Pass 043: Job Queue + Idempotency + Lease Protocol

Implements:
  INV-Q1  ARTIFACT_COMMIT_GATE      — mark_succeeded() enforces all required artifacts committed
  INV-Q2  IDEMPOTENCY_KEY_DEDUP    — same key returns existing run_id, never creates a duplicate
  INV-Q3  REQUIRED_ARTIFACT_REGISTRY_CENTRALIZED — artifact types defined once, queried by barrier

Scope: additive only. No pipeline, signal, policy, or renderer logic.
"""
from __future__ import annotations

import hashlib
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from packages.db.models import Artifact, Run, utcnow

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_ATTEMPTS: int = 3
DEFAULT_LEASE_SECONDS: int = 300   # 5 min; heartbeat must fire before this expires

# INV-Q3: The canonical set of artifact_type values that must be committed before
# a run can be marked succeeded. To add a new required artifact to the pipeline,
# add its type string here. Adding it anywhere else is insufficient — the barrier
# won't catch it.
REQUIRED_ARTIFACT_TYPES: frozenset[str] = frozenset({
    "evidence_graph",   # evidence_graph.json — powers the audit/review UI
    "output_pdf",       # attorney-facing chronology PDF
    "acceptance_check", # acceptance gate result JSON
})

# Status constants — queue-layer names. The API serialization layer maps
# "queued" → "pending" and "succeeded" → "success" to preserve the
# Status Compatibility Matrix (runs.py). Never change these without updating
# the serializer and the Status Compatibility Matrix in AGENTS.md.
STATUS_QUEUED    = "queued"
STATUS_RUNNING   = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED    = "failed"
STATUS_CANCELED  = "canceled"

# Statuses that block a new run from being created for the same idempotency key.
_BLOCK_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING, STATUS_SUCCEEDED})


def _worker_id() -> str:
    """Stable worker identifier: hostname + PID."""
    return f"{socket.gethostname()}-{os.getpid()}"


# ── Idempotency key ───────────────────────────────────────────────────────────

def build_idempotency_key(
    firm_id: str,
    packet_sha256: str,
    export_mode: str,
    policy_version: str,
    signal_layer_version: str,
) -> str:
    """Deterministic run deduplication key.

    SCOPE NOTE: This key is intentionally policy-bound.
    If policy_version or signal_layer_version bumps, the key changes and a NEW
    run is created. That is correct — a policy change means we want a fresh
    result, not the cached one. Do not remove these fields from the key to
    "fix" apparent duplicates after a policy bump — those are intentional new
    runs, not bugs.

    Idempotency scope:
      Same firm + same packet + re-upload           → same key → existing run_id
      Same firm + same packet + policy_version bump → new key  → new run
      Same firm + same packet + signal_layer bump   → new key  → new run
      Same firm + different packet                  → new key  → new run
    """
    raw = "|".join([
        str(firm_id),
        str(packet_sha256),
        str(export_mode).upper(),
        str(policy_version),
        str(signal_layer_version),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Queue operations ──────────────────────────────────────────────────────────

def enqueue_run(
    db: Session,
    run_id: str,
    idempotency_key: str,
) -> tuple[str, bool]:
    """Enqueue a run or return an existing one if the key already exists.

    INV-Q2: If a run with the same idempotency_key exists and its status is
    queued/running/succeeded, returns that run_id without creating a new row.
    If status is failed and attempts < MAX_ATTEMPTS, re-queues the existing
    run (same run_id, incremented attempt). Dead-letter after MAX_ATTEMPTS.

    Returns:
        (run_id, created): created=True if a new row was inserted.

    Raises:
        RuntimeError: if status=failed and attempts >= MAX_ATTEMPTS (dead-letter)
    """
    existing = (
        db.query(Run)
        .filter(Run.idempotency_key == idempotency_key)
        .first()
    )

    if existing is not None:
        if existing.status in _BLOCK_STATUSES:
            logger.info(
                "enqueue_run: idempotency hit — returning existing run_id=%s status=%s",
                existing.id, existing.status,
            )
            return existing.id, False

        if existing.status == STATUS_FAILED:
            if existing.attempt >= MAX_ATTEMPTS:
                raise RuntimeError(
                    f"Run {existing.id} has reached MAX_ATTEMPTS={MAX_ATTEMPTS} — dead-lettered. "
                    f"Manually inspect before requeueing."
                )
            # Re-queue: same run_id, increment attempt
            existing.status = STATUS_QUEUED
            existing.attempt += 1
            existing.lock_expires_at = None
            existing.worker_id = None
            existing.error_message = None
            db.flush()
            logger.info(
                "enqueue_run: re-queued failed run run_id=%s attempt=%d",
                existing.id, existing.attempt,
            )
            return existing.id, False

        if existing.status == STATUS_CANCELED:
            # Treat canceled as retriable — same as failed but no attempt cap check here.
            existing.status = STATUS_QUEUED
            existing.attempt += 1
            existing.lock_expires_at = None
            existing.worker_id = None
            db.flush()
            return existing.id, False

    # New run — update the row that was pre-inserted by the caller, or insert here.
    # Callers are expected to have already created the Run row with id=run_id
    # and status="queued" before calling enqueue_run. We set the idempotency_key.
    row = db.query(Run).filter(Run.id == run_id).first()
    if row is None:
        raise RuntimeError(f"enqueue_run: run_id={run_id} not found in DB — create the Run row first")
    row.idempotency_key = idempotency_key
    row.status = STATUS_QUEUED
    row.attempt = 1
    db.flush()
    logger.info("enqueue_run: new run queued run_id=%s", run_id)
    return run_id, True


def claim_next_run(
    db: Session,
    worker_id: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> Run | None:
    """Claim the next queued run using a pessimistic lock.

    Uses SELECT ... FOR UPDATE SKIP LOCKED (Postgres) to ensure exclusive
    claim — two workers cannot both claim the same run.

    Sets status=running, locked_by (worker_id column), lock_expires_at, attempt+=0
    (attempt was already incremented at enqueue).

    Returns the claimed Run row, or None if no queued runs exist.
    """
    wid = worker_id or _worker_id()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)

    try:
        # Postgres: FOR UPDATE SKIP LOCKED prevents two workers racing.
        run = (
            db.query(Run)
            .filter(Run.status == STATUS_QUEUED)
            .order_by(Run.created_at.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
    except Exception:
        # Fallback for SQLite in tests (no SKIP LOCKED support).
        run = (
            db.query(Run)
            .filter(Run.status == STATUS_QUEUED)
            .order_by(Run.created_at.asc())
            .first()
        )

    if run is None:
        return None

    run.status = STATUS_RUNNING
    run.worker_id = wid
    run.lock_expires_at = expires_at
    run.started_at = utcnow()
    run.claimed_at = utcnow()
    db.flush()
    logger.info("claim_next_run: claimed run_id=%s worker=%s", run.id, wid)
    return run


def heartbeat(
    db: Session,
    run_id: str,
    worker_id: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> None:
    """Extend the lease on a running run. Must be called every ~60s.

    Only extends if the calling worker still owns the lease (guards against
    a race where the sweeper already reclaimed the run).
    """
    wid = worker_id or _worker_id()
    new_expires = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
    updated = (
        db.query(Run)
        .filter(Run.id == run_id, Run.worker_id == wid, Run.status == STATUS_RUNNING)
        .update({"lock_expires_at": new_expires, "heartbeat_at": utcnow()})
    )
    db.flush()
    if not updated:
        logger.warning("heartbeat: no update for run_id=%s worker=%s — run may have been reclaimed", run_id, wid)


def mark_succeeded(db: Session, run_id: str) -> None:
    """Mark a run as succeeded.

    INV-Q1 + INV-Q3: Raises RuntimeError if any artifact whose type is in
    REQUIRED_ARTIFACT_TYPES is either absent or not write_state='committed'.
    The check queries the central registry — it never hardcodes artifact names inline.
    """
    # Find which required types are present and committed
    committed_types = {
        row.artifact_type
        for row in db.query(Artifact.artifact_type)
        .filter(
            Artifact.run_id == run_id,
            Artifact.artifact_type.in_(REQUIRED_ARTIFACT_TYPES),
            Artifact.write_state == "committed",
        )
        .all()
    }
    missing_or_uncommitted = REQUIRED_ARTIFACT_TYPES - committed_types
    if missing_or_uncommitted:
        raise RuntimeError(
            f"INV-Q1 violated: required artifact(s) missing or not committed for run {run_id}: "
            f"{sorted(missing_or_uncommitted)}"
        )

    now = utcnow()
    db.query(Run).filter(Run.id == run_id).update({
        "status": STATUS_SUCCEEDED,
        "finished_at": now,
        "lock_expires_at": None,
        "worker_id": None,
    })
    db.flush()
    logger.info("mark_succeeded: run_id=%s", run_id)


def mark_failed(
    db: Session,
    run_id: str,
    error_class: str | None = None,
    error_message: str | None = None,
) -> None:
    """Mark a run as failed. Records error_class and message."""
    now = utcnow()
    db.query(Run).filter(Run.id == run_id).update({
        "status": STATUS_FAILED,
        "finished_at": now,
        "lock_expires_at": None,
        "worker_id": None,
        "error_class": error_class,
        "error_message": (error_message or "")[:2000],  # truncate for DB safety
    })
    db.flush()
    logger.warning("mark_failed: run_id=%s error_class=%s", run_id, error_class)


def mark_canceled(db: Session, run_id: str) -> None:
    """Best-effort cancel. Worker checks for this between stages."""
    db.query(Run).filter(
        Run.id == run_id,
        Run.status.in_([STATUS_QUEUED, STATUS_RUNNING]),
    ).update({
        "status": STATUS_CANCELED,
        "finished_at": utcnow(),
        "lock_expires_at": None,
    })
    db.flush()
    logger.info("mark_canceled: run_id=%s", run_id)


def is_canceled(db: Session, run_id: str) -> bool:
    """Check if a run has been canceled. Workers call this between pipeline stages."""
    run = db.query(Run).filter(Run.id == run_id).first()
    return run is not None and run.status == STATUS_CANCELED


def requeue_expired_leases(
    db: Session,
    max_attempts: int = MAX_ATTEMPTS,
) -> int:
    """Sweeper: re-queue runs where status=running and lock has expired.

    If attempt >= max_attempts, marks as failed (dead-letter) instead of
    re-queueing. Returns the count of runs re-queued.
    """
    now = datetime.now(timezone.utc)
    expired_runs = (
        db.query(Run)
        .filter(Run.status == STATUS_RUNNING, Run.lock_expires_at < now)
        .all()
    )
    requeued = 0
    for run in expired_runs:
        if run.attempt >= max_attempts:
            run.status = STATUS_FAILED
            run.error_class = "max_attempts_exceeded"
            run.error_message = f"Dead-lettered after {run.attempt} attempts."
            run.finished_at = utcnow()
            run.lock_expires_at = None
            run.worker_id = None
            logger.warning("requeue_expired_leases: dead-lettered run_id=%s attempts=%d", run.id, run.attempt)
        else:
            run.status = STATUS_QUEUED
            run.attempt += 1
            run.lock_expires_at = None
            run.worker_id = None
            requeued += 1
            logger.info("requeue_expired_leases: requeued run_id=%s new_attempt=%d", run.id, run.attempt)
    db.flush()
    return requeued
