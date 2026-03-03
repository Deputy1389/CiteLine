# Pass 043 — Release Notes

**Title:** Queue + Idempotent Runs + Crash-Safe Artifacts
**Date:** 2026-03-02
**Scope:** Additive only — no pipeline, signal, policy, or renderer changes

---

## What Changed

### New invariants

| ID | Name | Rule |
|---|---|---|
| INV-Q1 | ARTIFACT_COMMIT_GATE | `mark_succeeded()` raises if any required artifact is absent or not committed |
| INV-Q2 | IDEMPOTENCY_KEY_DEDUP | Same key → same run_id; policy-bound scope |
| INV-Q3 | REQUIRED_ARTIFACT_REGISTRY_CENTRALIZED | Required artifact types defined in one frozenset |

### New files

| File | Purpose |
|---|---|
| `apps/worker/lib/queue.py` | Queue primitives: enqueue, claim, heartbeat, mark_succeeded/failed/canceled, requeue_expired_leases |
| `scripts/sweep_stuck_runs.py` | Sweeper: requeues expired leases, dead-letters after MAX_ATTEMPTS |
| `scripts/admin_queue.py` | Admin CLI: enqueue, status, requeue, cancel, list |
| `tests/unit/test_queue_idempotency.py` | 6 unit tests (all pass) |
| `tests/integration/test_worker_crash_recovery.py` | 2 integration tests (all pass) |

### Modified files

| File | Change |
|---|---|
| `packages/db/models.py` | `Run`: +`idempotency_key`, +`attempt`, +`lock_expires_at`; `Artifact`: +`write_state` |
| `apps/worker/lib/artifacts_writer.py` | +`write_artifact_atomic()`, +`mark_artifact_committed()` |
| `governance/invariants.md` | INV-Q1, INV-Q2, INV-Q3 registered |

---

## Test Results

```
tests/unit/test_queue_idempotency.py          6/6 PASS
tests/integration/test_worker_crash_recovery.py  2/2 PASS
Total: 8/8 PASS
```

---

## Acceptance Criteria Status

- [x] `REQUIRED_ARTIFACT_TYPES` registry defined centrally; `mark_succeeded()` queries it
- [x] Same idempotency key → same `run_id` (no duplicate run rows)
- [x] Policy bump → new idempotency key → new run (documented in code)
- [x] Failed run can be retried; `attempt` increments; same `run_id`
- [x] `mark_succeeded()` raises if any required type is absent or not committed
- [x] `claim_next_run()` is exclusive (two workers cannot both claim the same run)
- [x] Sweeper requeues expired leases; dead-letters after `MAX_ATTEMPTS=3`
- [x] Artifact writes atomic (`*.tmp` → `os.replace` → `committed`)
- [x] Cancellation check available via `is_canceled()` for worker stage gates
- [x] 8 tests pass
- [x] `governance/invariants.md` updated: INV-Q1 + INV-Q2 + INV-Q3
- [x] No pipeline, signal, policy, or renderer changes
- [x] API-facing status strings unchanged

---

## What This Pass Does NOT Do

- Does not change pipeline extraction, scoring, or rendering
- Does not add a web UI for queue status (admin CLI only)
- Does not implement Slack alerting for stuck runs
- Does not address field robustness sweep (Pass 044 scope)
