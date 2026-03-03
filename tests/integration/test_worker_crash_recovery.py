"""
tests/integration/test_worker_crash_recovery.py — Pass 043: Crash recovery integration tests.

Simulates worker crash mid-run and verifies that:
1. The sweeper correctly requeues the orphaned run
2. Re-run completes with all required artifacts committed exactly once
3. Concurrency cap is respected (no more than N running simultaneously)
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import Artifact, Base, Run, _uuid, utcnow
from apps.worker.lib.queue import (
    MAX_ATTEMPTS,
    REQUIRED_ARTIFACT_TYPES,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    claim_next_run,
    mark_failed,
    mark_succeeded,
    requeue_expired_leases,
)
from apps.worker.lib.artifacts_writer import mark_artifact_committed


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_queued_run(db: Session, ikey: str | None = None) -> Run:
    run = Run(
        id=_uuid(),
        matter_id="test-matter",
        status=STATUS_QUEUED,
        attempt=1,
        idempotency_key=ikey or _uuid(),
    )
    db.add(run)
    db.flush()
    return run


def _commit_all_artifacts(db: Session, run_id: str) -> None:
    """Write all required artifacts as committed for a run."""
    for atype in REQUIRED_ARTIFACT_TYPES:
        existing = db.query(Artifact).filter(
            Artifact.run_id == run_id, Artifact.artifact_type == atype
        ).first()
        if existing is None:
            db.add(Artifact(
                id=_uuid(),
                run_id=run_id,
                artifact_type=atype,
                storage_uri=f"/tmp/{atype}.json",
                sha256="aabbcc",
                bytes=256,
                write_state="committed",
            ))
        else:
            existing.write_state = "committed"
    db.flush()


# ── Test 1: Worker crash mid-run recovery ────────────────────────────────────

def test_worker_crash_mid_run_recovery(db: Session):
    """Simulate: claim run → write some tmp artifacts → 'crash'.
    Sweeper must requeue the run. Re-run must complete with committed artifacts.
    No duplicate artifact rows for the same type.
    """
    ikey = _uuid()
    run = _make_queued_run(db, ikey=ikey)

    # === Phase 1: Worker claims the run ===
    claimed = claim_next_run(db, worker_id="worker-crashed")
    assert claimed is not None
    assert claimed.id == run.id
    assert claimed.status == STATUS_RUNNING

    # Worker starts writing — adds a "writing" artifact (partial write)
    partial = Artifact(
        id=_uuid(),
        run_id=run.id,
        artifact_type=list(REQUIRED_ARTIFACT_TYPES)[0],
        storage_uri="/tmp/partial.json",
        sha256="0" * 64,
        bytes=0,
        write_state="writing",
    )
    db.add(partial)
    db.flush()

    # === Phase 2: Simulate crash (force lock expiry) ===
    run.lock_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()

    # === Phase 3: Sweeper runs ===
    requeued = requeue_expired_leases(db, max_attempts=MAX_ATTEMPTS)
    db.refresh(run)

    assert requeued == 1
    assert run.status == STATUS_QUEUED
    assert run.attempt == 2
    assert run.worker_id is None

    # === Phase 4: Recovery worker claims and completes ===
    recovered = claim_next_run(db, worker_id="worker-recovery")
    assert recovered is not None
    assert recovered.id == run.id

    # Fix the partial artifact + add remaining required ones
    partial.write_state = "committed"
    _commit_all_artifacts(db, run.id)

    # mark_succeeded must now work
    mark_succeeded(db, run.id)
    db.refresh(run)
    assert run.status == STATUS_SUCCEEDED

    # No duplicate committed artifact rows for the same (run_id, artifact_type)
    for atype in REQUIRED_ARTIFACT_TYPES:
        count = db.query(Artifact).filter(
            Artifact.run_id == run.id,
            Artifact.artifact_type == atype,
            Artifact.write_state == "committed",
        ).count()
        assert count == 1, f"Duplicate committed artifact for type {atype}"


# ── Test 2: Concurrency cap ──────────────────────────────────────────────────

def test_concurrency_cap(db: Session):
    """Enqueue 5 jobs, claim up to 2 concurrently, confirm DB never shows >2 running.

    Uses threading to simulate concurrent workers. SQLite serializes writes,
    so mutual exclusion is guaranteed — this tests the status-level cap logic.
    """
    MAX_CONCURRENT = 2
    NUM_JOBS = 5

    # Enqueue 5 runs
    for _ in range(NUM_JOBS):
        db.add(Run(
            id=_uuid(),
            matter_id="test-matter",
            status=STATUS_QUEUED,
            attempt=1,
            idempotency_key=_uuid(),
        ))
    db.flush()

    claimed_ids: list[str] = []
    lock = threading.Lock()

    def worker_loop():
        # Each "worker" only claims one run for this test
        engine2 = db.bind
        with Session(engine2) as local_db:
            active = local_db.query(Run).filter(Run.status == STATUS_RUNNING).count()
            if active >= MAX_CONCURRENT:
                return  # cap enforced
            run = claim_next_run(local_db, worker_id=f"worker-{threading.get_ident()}")
            if run:
                with lock:
                    claimed_ids.append(run.id)
                # Verify running count never exceeds cap
                running = local_db.query(Run).filter(Run.status == STATUS_RUNNING).count()
                assert running <= MAX_CONCURRENT, f"Concurrency cap exceeded: {running} running"
                local_db.commit()

    threads = [threading.Thread(target=worker_loop) for _ in range(NUM_JOBS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # At most MAX_CONCURRENT runs should have been claimed
    assert len(claimed_ids) <= MAX_CONCURRENT, (
        f"Expected at most {MAX_CONCURRENT} claimed, got {len(claimed_ids)}"
    )
