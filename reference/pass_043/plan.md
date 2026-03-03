# Pass 043 — Implementation Plan

**Title:** Queue + Idempotent Runs + Crash-Safe Artifacts
**Source:** `reference/Diagnosis.md`
**Checklist:** `reference/pass_043/checklist043.md`
**Scope:** Additive only — no pipeline, signal, policy, or renderer changes

> **Two critical architectural decisions baked into this plan:**
> 1. Required artifact types are centrally registered — not hardcoded in `mark_succeeded`.
> 2. Idempotency scope is explicitly policy-bound — a policy bump intentionally creates a new run.

---

## Context

After Pass 042 (observability), CiteLine can see what is happening in production. What it cannot do safely is handle concurrent uploads, worker crashes, or duplicate submissions. A single firm uploading a packet twice gets two runs. A worker crash leaves a run stuck in `running` forever. A partial artifact write is indistinguishable from a complete one.

This pass closes all three gaps by introducing a formal run lifecycle model with idempotency keys, a lease/claim queue protocol, and atomic artifact writes.

---

## Invariants This Pass Guarantees

| ID | Name | Rule |
|---|---|---|
| INV-Q1 | ARTIFACT_COMMIT_GATE | `mark_succeeded()` raises if any required artifact is not `committed` |
| INV-Q2 | IDEMPOTENCY_KEY_DEDUP | Same `(firm_id, packet_sha256, export_mode, policy_version)` → same `run_id`, no second run |

---

## Deliverables

### 1. DB Schema (`packages/db/models.py` + migration)

**Add to `Run` model:**

```python
idempotency_key: str (unique, not null)
attempt: int = 0
locked_by: str | None        # worker_id
lock_expires_at: datetime | None
started_at: datetime | None
finished_at: datetime | None
error_message: str | None
```

**Status enum** (extend or formalize):
```
queued | running | succeeded | failed | canceled
```
(Note: `succeeded` replaces `success` at the queue layer — map to existing DB values as needed; keep API-facing status strings unchanged to avoid Status Compatibility Matrix breaks.)

**Add `write_state` to `Artifact` model:**
```python
write_state: str = "committed"   # "writing" | "committed"
sha256: str | None
bytes: int | None
```

**Migration:** All new columns nullable or have defaults — old schema deploys safely first.

---

### 2. Required Artifact Registry (`apps/worker/lib/queue.py` — top of file)

Centralized definition of what constitutes a complete run. **Never inline this in `mark_succeeded`.**

```python
# The canonical list of artifact types that must be committed before a run
# can be marked succeeded. If you add a new required artifact to the pipeline,
# add it here. Omitting it here means the completion barrier won't catch it.
REQUIRED_ARTIFACT_TYPES: frozenset[str] = frozenset({
    "evidence_graph",   # evidence_graph.json — powers the audit UI
    "output_pdf",       # the attorney-facing chronology PDF
    "acceptance_check", # acceptance gate result JSON
})
```

The `mark_succeeded` barrier then queries against this registry:

```python
def mark_succeeded(db, run_id: str) -> None:
    """INV-Q1: raises if any required artifact is not committed."""
    uncommitted = (
        db.query(Artifact)
          .filter(
              Artifact.run_id == run_id,
              Artifact.artifact_type.in_(REQUIRED_ARTIFACT_TYPES),
              Artifact.write_state != "committed",
          )
          .count()
    )
    if uncommitted > 0:
        raise RuntimeError(
            f"INV-Q1 violated: {uncommitted} required artifact(s) not committed for run {run_id}"
        )
    # Set terminal status
    db.query(Run).filter_by(run_id=run_id).update(
        {"status": "succeeded", "finished_at": datetime.utcnow()}
    )
    db.commit()
```

---

### 3. Queue Module (`apps/worker/lib/queue.py` — new file)

```python
def enqueue_run(db, idempotency_key, packet_path, export_mode, firm_id) -> str:
    """Return existing run_id if key exists and status in (queued, running, succeeded).
    If failed, increment attempt and re-queue. Never create a second run row."""

def claim_next_run(db, worker_id, lease_seconds=300) -> Run | None:
    """SELECT ... FOR UPDATE SKIP LOCKED. Sets status=running, locked_by, lock_expires_at."""

def heartbeat(db, run_id, worker_id, lease_seconds=300):
    """Extend lock_expires_at. Must be called every ~60s by worker."""

def mark_succeeded(db, run_id):
    """Raises RuntimeError if any required artifact is write_state=writing.
    Sets status=succeeded, finished_at."""

def mark_failed(db, run_id, error_class, message):
    """Sets status=failed (or queued if attempt < MAX_ATTEMPTS). Records error."""

def requeue_expired_leases(db, max_attempts=3) -> int:
    """Sweeper: re-queue runs where status=running AND lock_expires_at < now().
    Returns count of re-queued runs."""
```

**Design rules:**
- `enqueue_run` is the only code path that creates a `Run` row. No other code inserts runs.
- `mark_succeeded` is the only code path that sets `status=succeeded`. It enforces INV-Q1.
- `claim_next_run` uses `FOR UPDATE SKIP LOCKED` (Postgres) — two workers cannot both claim the same run.

---

### 4. Idempotency Key Design

```python
def build_idempotency_key(firm_id, packet_sha256, export_mode, policy_version, signal_layer_version) -> str:
    # SCOPE NOTE: This key is intentionally policy-bound.
    # If policy_version or signal_layer_version bumps, the key changes and a NEW run is created.
    # This is correct behavior: a policy change means we want a fresh result, not the cached one.
    # Do not remove policy_version or signal_layer_version from this key to "fix" apparent duplicates
    # after a policy bump — those are intentional new runs, not bugs.
    raw = f"{firm_id}|{packet_sha256}|{export_mode}|{policy_version}|{signal_layer_version}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

Key rules:
- Computed before enqueue. Stored on `Run` row at insert.
- On retry (failed run with **same** key), the **same** `run_id` is reused — `attempt` incremented.
- `MAX_ATTEMPTS = 3`. After 3 failures, `status = failed` permanently (dead-letter).
- Policy bump → new key → new run → old run untouched. This is by design.

**Idempotency scope summary:**

| Scenario | Key changes? | Result |
|---|---|---|
| Same firm, same packet, re-upload | No | Returns existing `run_id` |
| Same firm, same packet, `policy_version` bumped | Yes | New run created |
| Same firm, same packet, `signal_layer_version` bumped | Yes | New run created |
| Same firm, different packet | Yes | New run created |

---

### 5. Atomic Artifact Writes (`apps/worker/lib/artifacts_writer.py`)

Update `write_artifact_json` and `write_evidence_graph_artifact`:

```python
def write_artifact_atomic(path: Path, content: bytes | str) -> None:
    """Write to *.tmp, then atomic rename to final path."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content if isinstance(content, bytes) else content.encode())
    tmp.rename(path)   # atomic on POSIX; best-effort on Windows (os.replace)
```

Update artifact DB record to `write_state = "committed"` only after rename succeeds.

Add a "run completion barrier" in `mark_succeeded()`:
```python
uncommitted = db.query(Artifact).filter_by(run_id=run_id, write_state="writing").count()
if uncommitted > 0:
    raise RuntimeError(f"INV-Q1 violated: {uncommitted} artifact(s) still writing for run {run_id}")
```

---

### 6. Worker Update (`apps/worker/pipeline.py` or runner)

```python
# Concurrency cap
MAX_CONCURRENT = int(os.environ.get("WORKER_CONCURRENCY", 2))

while True:
    if active_count() >= MAX_CONCURRENT:
        time.sleep(1)
        continue
    run = claim_next_run(db, worker_id=WORKER_ID)
    if run is None:
        time.sleep(POLL_INTERVAL)
        continue
    threading.Thread(target=process_run, args=(run,), daemon=True).start()
```

Check for cancellation between stages:
```python
if db.query(Run).filter_by(run_id=run_id, status="canceled").count():
    return  # best-effort cancel
```

---

### 7. Sweeper Script (`scripts/sweep_stuck_runs.py` — new)

```python
# Usage: python scripts/sweep_stuck_runs.py [--dry-run]
# Requeues expired leases, reports dead-letters, prints summary.
requeued = requeue_expired_leases(db, max_attempts=MAX_ATTEMPTS)
dead = db.query(Run).filter_by(status="failed").count()
print(f"Requeued: {requeued}  Dead-letter: {dead}")
```

Run this as a cron / systemd timer every 2 minutes on the worker host.

---

### 8. Minimal Admin CLI (`scripts/run_worker.py` update or new `scripts/admin_queue.py`)

```bash
python scripts/admin_queue.py enqueue --packet path/to/packet.pdf --mode INTERNAL --firm-id abc123
python scripts/admin_queue.py status --run-id <run_id>
python scripts/admin_queue.py requeue --run-id <run_id>   # only if failed
python scripts/admin_queue.py cancel  --run-id <run_id>   # best-effort
```

---

### 9. Tests (`tests/unit/test_queue_idempotency.py` + `tests/integration/test_worker_crash_recovery.py`)

**Unit (6 tests):**
```python
def test_idempotency_key_same_input_returns_same_run()
def test_idempotency_key_failed_allows_retry_same_run_id_attempt_increments()
def test_claim_next_run_lease_exclusive()
def test_lease_expiry_requeues()
def test_atomic_artifact_write_committed_only()
def test_mark_succeeded_requires_all_required_artifacts_committed()
```

**Integration (2 tests):**
```python
def test_worker_crash_mid_run_recovery()
def test_concurrency_cap()
```

---

### 10. Governance Update (`governance/invariants.md`)

Add:

```
### INV-Q1 — ARTIFACT_COMMIT_GATE
A run cannot be marked succeeded unless all required artifacts are write_state=committed.
Enforced in: apps/worker/lib/queue.py :: mark_succeeded()
Tested in: tests/unit/test_queue_idempotency.py
Introduced: Pass 043

### INV-Q2 — IDEMPOTENCY_KEY_DEDUP
Duplicate enqueue requests for same (firm_id, packet_sha256, export_mode, policy_version)
return the existing run_id without creating a new run.
Enforced in: apps/worker/lib/queue.py :: enqueue_run()
Tested in: tests/unit/test_queue_idempotency.py
Introduced: Pass 043
```

---

## Step-by-Step Order

```
Step 1  — DB: add idempotency_key, lock columns, attempt to Run model + migration
Step 2  — DB: add write_state, sha256, bytes to Artifact model + migration
Step 3  — queue.py: define REQUIRED_ARTIFACT_TYPES registry (centralized)
Step 4  — queue.py: enqueue_run() with idempotency guard (INV-Q2) + policy-bound key comment
Step 5  — queue.py: claim_next_run() with SKIP LOCKED
Step 6  — queue.py: heartbeat(), mark_succeeded() querying REQUIRED_ARTIFACT_TYPES (INV-Q1)
Step 7  — queue.py: mark_failed(), requeue_expired_leases()
Step 8  — artifacts_writer.py: atomic write + committed flag update
Step 9  — pipeline.py / worker runner: concurrency cap + heartbeat thread + cancel check
Step 10 — scripts/sweep_stuck_runs.py
Step 11 — scripts/admin_queue.py (enqueue/status/requeue/cancel)
Step 12 — Unit tests (6): test_queue_idempotency.py
Step 13 — Integration tests (2): test_worker_crash_recovery.py
Step 14 — governance/invariants.md: add INV-Q1 and INV-Q2
Step 15 — Full regression: CASES: 6/6 STATIC: PASS DRIFT: PASS
Step 16 — release_notes.md
```

---

## Acceptance Criteria

- [ ] `REQUIRED_ARTIFACT_TYPES` registry defined centrally in `queue.py`; `mark_succeeded()` queries it, never hardcodes artifact names
- [ ] Same idempotency key → same `run_id` (no duplicate run rows)
- [ ] Policy bump → new idempotency key → new run (policy-bound scope documented in code)
- [ ] Failed run can be retried; `attempt` increments; same `run_id`
- [ ] `mark_succeeded()` raises if any artifact in `REQUIRED_ARTIFACT_TYPES` is not `committed`
- [ ] `claim_next_run()` is exclusive — concurrent callers cannot both claim the same run
- [ ] Sweeper requeues expired leases. Dead-letters after `MAX_ATTEMPTS=3`.
- [ ] Concurrency cap respected — never more than N `running` simultaneously
- [ ] Artifact writes atomic (`*.tmp` → rename → `committed`)
- [ ] Worker checks cancellation between stages
- [ ] 6 unit tests pass in `test_queue_idempotency.py`
- [ ] 2 integration tests pass in `test_worker_crash_recovery.py`
- [ ] `governance/invariants.md` updated: INV-Q1 + INV-Q2
- [ ] Full regression: `CASES: 6/6 STATIC: PASS DRIFT: PASS`
- [ ] No pipeline, signal, policy, or renderer changes
- [ ] API-facing status strings unchanged (Status Compatibility Matrix holds)

---

## Key Risks

| Risk | Mitigation |
|---|---|
| `FOR UPDATE SKIP LOCKED` not available on SQLite | Use Postgres in production; test harness may need a Postgres fixture or mock |
| Atomic rename not atomic on Windows (os.replace) | Use `os.replace()` which is atomic on Windows NTFS — acceptable for local dev |
| Worker crash during heartbeat renew | Lease expiry sweeper recovers within one sweep interval (2 min default) |
| mark_succeeded raises, leaving run stuck in running | Caller catches and calls mark_failed — never leaves run in terminal-pending limbo |
| Status string mismatch (`succeeded` vs `success`) | Map queue-layer `succeeded` to API-layer `success` at the serialization boundary only |

---

## What This Pass Does NOT Do

- Does not change pipeline extraction, scoring, or rendering
- Does not add a web UI for queue status (admin CLI only)
- Does not implement Slack alerting for stuck runs (documented — sweeper logs to stdout)
- Does not change any policy parameters or signal layer logic
- Does not address field robustness sweep (Gap 2 in Diagnosis.md — Pass 044 scope)
