"""
tests/unit/test_queue_idempotency.py — Pass 043: Queue invariant unit tests.

Tests INV-Q1 (ARTIFACT_COMMIT_GATE), INV-Q2 (IDEMPOTENCY_KEY_DEDUP),
and INV-Q3 (REQUIRED_ARTIFACT_REGISTRY_CENTRALIZED).

Uses SQLite in-memory for speed. Postgres-specific FOR UPDATE SKIP LOCKED
behavior is tested implicitly via the claim fallback path.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import Session

from packages.db.models import Base, Run, Artifact, _uuid, utcnow
from apps.worker.lib.queue import (
    MAX_ATTEMPTS,
    REQUIRED_ARTIFACT_TYPES,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_CANCELED,
    build_idempotency_key,
    claim_next_run,
    enqueue_run,
    heartbeat,
    mark_failed,
    mark_succeeded,
    requeue_expired_leases,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_run(db: Session, status: str = STATUS_QUEUED, attempt: int = 1, ikey: str | None = None) -> Run:
    """Helper: insert a Run row and return it."""
    run = Run(
        id=_uuid(),
        matter_id="test-matter",
        status=status,
        attempt=attempt,
        idempotency_key=ikey or _uuid(),
    )
    db.add(run)
    db.flush()
    return run


def _add_artifact(db: Session, run_id: str, artifact_type: str, write_state: str = "committed") -> Artifact:
    art = Artifact(
        id=_uuid(),
        run_id=run_id,
        artifact_type=artifact_type,
        storage_uri=f"/tmp/{artifact_type}.json",
        sha256="abc123",
        bytes=100,
        write_state=write_state,
    )
    db.add(art)
    db.flush()
    return art


# ── Test 1: INV-Q2 — same idempotency key returns same run_id ───────────────

def test_idempotency_key_same_input_returns_same_run(db: Session):
    """INV-Q2: Duplicate enqueue with same key → same run_id, no new row created."""
    ikey = build_idempotency_key("firm1", "abc", "INTERNAL", "v1", "v36")
    run = _make_run(db, status=STATUS_QUEUED, ikey=ikey)
    enqueue_run(db, run.id, ikey)  # first call — sets/confirms the key

    # Simulate a duplicate request: create a new run_id, but same key
    new_run_id = _uuid()
    new_row = Run(id=new_run_id, matter_id="test-matter", status=STATUS_QUEUED, attempt=1)
    db.add(new_row)
    db.flush()

    returned_id, created = enqueue_run(db, new_run_id, ikey)
    assert not created, "Should NOT create a new run"
    assert returned_id == run.id, "Should return the original run_id"

    # Confirm the DB has only ONE run with this idempotency key
    count = db.query(Run).filter(Run.idempotency_key == ikey).count()
    assert count == 1


# ── Test 2: INV-Q2 — failed run allows retry, same run_id, attempt increments

def test_idempotency_key_failed_allows_retry_same_run_id_attempt_increments(db: Session):
    """INV-Q2: Failed run can be retried; attempt increments; run_id stays the same."""
    ikey = build_idempotency_key("firm2", "def", "MEDIATION", "v1", "v36")
    run = _make_run(db, status=STATUS_FAILED, attempt=1, ikey=ikey)

    new_run_id = _uuid()
    new_row = Run(id=new_run_id, matter_id="test-matter", status=STATUS_QUEUED, attempt=1)
    db.add(new_row)
    db.flush()

    returned_id, created = enqueue_run(db, new_run_id, ikey)
    assert returned_id == run.id
    assert not created

    db.refresh(run)
    assert run.status == STATUS_QUEUED
    assert run.attempt == 2


# ── Test 3: Exclusive lease — two workers can't claim the same run ───────────

def test_claim_next_run_lease_exclusive(db: Session):
    """Two sequential claim calls should claim different runs (not the same one)."""
    run1 = _make_run(db, STATUS_QUEUED)
    run2 = _make_run(db, STATUS_QUEUED)

    claimed1 = claim_next_run(db, worker_id="worker-A")
    # Mark it running before the second claim
    claimed2 = claim_next_run(db, worker_id="worker-B")

    assert claimed1 is not None
    assert claimed2 is not None
    assert claimed1.id != claimed2.id, "Two workers must not claim the same run"


# ── Test 4: Lease expiry requeues ────────────────────────────────────────────

def test_lease_expiry_requeues(db: Session):
    """Sweeper requeues runs where lock_expires_at is in the past."""
    run = _make_run(db, STATUS_RUNNING, attempt=1)
    # Force the lock to be expired
    run.lock_expires_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    db.flush()

    requeued = requeue_expired_leases(db, max_attempts=MAX_ATTEMPTS)
    db.refresh(run)

    assert requeued == 1
    assert run.status == STATUS_QUEUED
    assert run.attempt == 2
    assert run.worker_id is None


# ── Test 5: Atomic artifact write — committed only visible ───────────────────

def test_atomic_artifact_write_committed_only(db: Session):
    """write_state='writing' artifacts must not satisfy the INV-Q1 barrier."""
    from apps.worker.lib.artifacts_writer import write_artifact_atomic
    import tempfile, os
    from pathlib import Path

    run = _make_run(db, STATUS_RUNNING)

    # Add all required artifacts as committed except one
    required = list(REQUIRED_ARTIFACT_TYPES)
    for atype in required[:-1]:
        _add_artifact(db, run.id, atype, write_state="committed")
    # The last one is still writing
    _add_artifact(db, run.id, required[-1], write_state="writing")

    with pytest.raises(RuntimeError, match="INV-Q1"):
        mark_succeeded(db, run.id)

    # Fix it: set to committed
    db.query(Artifact).filter(
        Artifact.run_id == run.id, Artifact.artifact_type == required[-1]
    ).update({"write_state": "committed"})
    db.flush()

    # Now mark_succeeded should pass
    mark_succeeded(db, run.id)
    db.refresh(run)
    assert run.status == STATUS_SUCCEEDED


# ── Test 6: INV-Q1 — mark_succeeded raises if required artifact not committed ─

def test_mark_succeeded_requires_all_required_artifacts_committed(db: Session):
    """INV-Q1 + INV-Q3: mark_succeeded raises if any REQUIRED_ARTIFACT_TYPES entry is
    not committed. Adding a new type to the registry automatically enforces the barrier
    without changing mark_succeeded itself."""
    run = _make_run(db, STATUS_RUNNING)

    # No artifacts at all — barrier fires
    with pytest.raises(RuntimeError, match="INV-Q1"):
        mark_succeeded(db, run.id)

    # Add all required types as committed
    for atype in REQUIRED_ARTIFACT_TYPES:
        _add_artifact(db, run.id, atype, write_state="committed")

    # Now it should succeed
    mark_succeeded(db, run.id)
    db.refresh(run)
    assert run.status == STATUS_SUCCEEDED
    assert run.finished_at is not None
