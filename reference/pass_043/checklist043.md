# Pass 043 — Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`
>
> Complete ALL sections before writing any implementation plan.
> No sections collapsed. No categories skipped.
> If these conditions are not met, implementation is forbidden.

---

## PASS TITLE

**Pass 043 — Queue + Idempotent Runs + Crash-Safe Artifacts**

---

## 1. System State

**Stage**: Hardening → Productization (Pilot Readiness)

**Signal layer status**: Locked at Pass 36

**Leverage layer status**: Implemented at Pass 37

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

Without a job queue and idempotency guarantees, onboarding a pilot firm is actively dangerous. A worker crash or double-trigger can create duplicate runs, leave partial artifacts, or produce "done but missing" states that the attorney sees. This pass makes failure modes explicit, bounded, and recoverable. It does not touch pipeline logic, signals, or renderer — it only wraps the execution layer in a safe harness.

**Active stage constraints:**

- No policy/weights changes
- No renderer inference changes
- No extraction behavior changes (unless required for idempotence)
- Determinism must remain stable
- Observability must not block completion (Pass 042 principle)

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [x] **Trust erosion risk**
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

**Which one is primary?**

Trust erosion risk — an attorney (or pilot firm) uploading a packet and seeing a duplicate run, missing artifacts, or a "succeeded" run with no PDF cannot trust the system. This is a pre-revenue existential risk.

**Optional secondary (only if tightly related):**

Architectural coupling — the worker currently has no lease/claim model, so crash recovery is undefined.

**Why is this the highest risk right now?**

Pass 042 added observability. The next blocker for onboarding a pilot is operational safety: the system cannot safely handle concurrent uploads, retries, or worker crashes. Without this pass, the first demo with a real firm under real load will be fragile.

---

## 3. Define the Failure Precisely

**What test fails today?**

No test exists for idempotent enqueue — submitting the same packet twice creates two runs. No test exists for crash recovery — a worker dying mid-run leaves an orphaned `running` status indefinitely.

**What artifact proves the issue?**

The `runs` table ORM model (`packages/db/models.py`) has no `idempotency_key`, `locked_by`, `lock_expires_at`, or `attempt` columns. The `artifacts` table has no `write_state` column.

**Is this reproducible across packets?**

Yes — systemic. Any packet submitted twice, or any worker restart, triggers the failure pattern.

**Is this systemic or packet-specific?**

Systemic — the entire execution harness is missing these guarantees.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- Two workers claiming the same run simultaneously
- A run being marked `succeeded` with uncommitted required artifacts
- A duplicate run created for the same idempotency key when the original is queued/running/succeeded

**Must be guaranteed:**

- A worker crash (simulated) results in the run being re-queued by the sweeper within one lease period
- Re-queue completes with the same `run_id`, incremented `attempt`, and all required artifacts committed once
- Concurrency cap N is never exceeded in steady state

**Must pass deterministically:**

- `test_idempotency_key_same_input_returns_same_run` passes 100%
- `test_lease_expiry_requeues` passes 100%
- `test_mark_succeeded_requires_all_required_artifacts_committed` passes 100%
- Full regression: `CASES: 6/6 STATIC: PASS DRIFT: PASS`

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

- [x] Adding boundary enforcement? (lease model, concurrency cap)
- [x] Introducing a guard pattern? (artifact write_state barrier; idempotency key guard)
- [ ] Consolidating logic?
- [ ] Eliminating duplication?
- [x] Separating layers more cleanly? (queue.py distinct from worker loop)

**Describe the move:**

The execution layer is split into three distinct concerns: (1) a **queue** with a formal claim/lease/heartbeat protocol, (2) a **worker** that claims and executes within a concurrency cap, and (3) an **artifact writer** with atomic write + committed state. The idempotency key acts as a deduplication guard at enqueue time. This turns run execution from "fire and hope" into a formal state machine.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-Q1

**Name**: ARTIFACT_COMMIT_GATE

**What must always be true after this pass?**

A run cannot be marked `succeeded` unless all required artifacts have `write_state = committed`.

**Where is it enforced?**

`apps/worker/lib/queue.py :: mark_succeeded()` — raises if any required artifact is not committed.

**Where is it tested?**

`tests/unit/test_queue_idempotency.py :: test_mark_succeeded_requires_all_required_artifacts_committed`

**What is added to `governance/invariants.md`?**

```
### INV-Q1 — ARTIFACT_COMMIT_GATE

A run cannot be marked succeeded unless all required artifacts are in write_state=committed.

Enforced in: apps/worker/lib/queue.py :: mark_succeeded()
Tested in: tests/unit/test_queue_idempotency.py
Introduced: Pass 043
Failure class protected: Trust erosion (succeeded run with missing artifacts)
```

**Invariant ID**: INV-Q3

**Name**: REQUIRED_ARTIFACT_REGISTRY_CENTRALIZED

**What must always be true after this pass?**

The set of artifact types required for run completion is defined in exactly one place (`REQUIRED_ARTIFACT_TYPES` in `queue.py`). `mark_succeeded()` queries this registry; it never hardcodes artifact names inline.

**Where is it enforced?**

`apps/worker/lib/queue.py` — `REQUIRED_ARTIFACT_TYPES` constant + `mark_succeeded()` filter query.

**Where is it tested?**

`tests/unit/test_queue_idempotency.py :: test_mark_succeeded_requires_all_required_artifacts_committed` — verified by adding a new type to the registry and confirming the barrier fires without any change to `mark_succeeded` itself.

**What is added to `governance/invariants.md`?**

```
### INV-Q3 — REQUIRED_ARTIFACT_REGISTRY_CENTRALIZED

The set of artifact types required for run completion is defined once in
REQUIRED_ARTIFACT_TYPES (queue.py). mark_succeeded() never hardcodes artifact names.

Enforced in: apps/worker/lib/queue.py :: REQUIRED_ARTIFACT_TYPES + mark_succeeded()
Tested in: tests/unit/test_queue_idempotency.py
Introduced: Pass 043
Failure class protected: Silent succeeded-with-missing-artifact as pipeline adds new artifact types
```

---

**Invariant ID**: INV-Q2

**Name**: IDEMPOTENCY_KEY_DEDUP

**What must always be true after this pass?**

Submitting the same packet, export_mode, and policy_version to the same firm never creates a second run if the original is queued, running, or succeeded.

**Idempotency scope is policy-bound.** When `policy_version` or `signal_layer_version` changes, the key changes and a new run is intentionally created. This is correct — a policy bump means we want a fresh result. Do not remove these fields from the key to "fix" apparent duplicates after a policy bump.

**Where is it enforced?**

`apps/worker/lib/queue.py :: enqueue_run()` — checks idempotency_key uniqueness before inserting.

**Where is it tested?**

`tests/unit/test_queue_idempotency.py :: test_idempotency_key_same_input_returns_same_run`

**What is added to `governance/invariants.md`?**

```
### INV-Q2 — IDEMPOTENCY_KEY_DEDUP

Duplicate enqueue requests for the same (firm_id, packet_sha256, export_mode, policy_version)
return the existing run_id without creating a new run.

Enforced in: apps/worker/lib/queue.py :: enqueue_run()
Tested in: tests/unit/test_queue_idempotency.py
Introduced: Pass 043
Failure class protected: Duplicate runs and artifacts
```

---

## 7. Tests Added

**Unit tests:**

- `tests/unit/test_queue_idempotency.py :: test_idempotency_key_same_input_returns_same_run` — same key returns same run_id, no INSERT
- `tests/unit/test_queue_idempotency.py :: test_idempotency_key_failed_allows_retry_same_run_id_attempt_increments` — failed run can be retried; attempt increments
- `tests/unit/test_queue_idempotency.py :: test_claim_next_run_lease_exclusive` — two concurrent callers cannot both claim the same run
- `tests/unit/test_queue_idempotency.py :: test_lease_expiry_requeues` — sweeper re-queues runs with expired lock_expires_at
- `tests/unit/test_queue_idempotency.py :: test_atomic_artifact_write_committed_only` — reader sees only committed artifacts; tmp is invisible
- `tests/unit/test_queue_idempotency.py :: test_mark_succeeded_requires_all_required_artifacts_committed` — mark_succeeded raises if any required artifact is writing

**Integration tests (if any):**

- `tests/integration/test_worker_crash_recovery.py :: test_worker_crash_mid_run_recovery` — simulate claim, write tmp, "crash", run sweeper, verify re-run completes with committed artifacts and no duplicates
- `tests/integration/test_worker_crash_recovery.py :: test_concurrency_cap` — enqueue 5 jobs, run worker with concurrency=2, assert DB never shows >2 `running` simultaneously

**Determinism comparison:**

Standard full regression: `CASES: 6/6 STATIC: PASS DRIFT: PASS` (no signal/policy changes, so determinism is trivially stable)

**Artifact-level assertion:**

- `reference/pass_043/regression_report.json` must show `overall_pass: true`

**Total new tests:** 8 (6 unit + 2 integration)

---

## 8. Risk Reduced

This pass reduces which risks:

- [x] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Maintenance cost
- [ ] Manual review time

**Explain how each checked risk is reduced:**

- **Legal risk**: No more "succeeded" run without provably committed artifacts. Every attorney-facing PDF is backed by a committed artifact record.
- **Trust risk**: Pilot firms can upload without fear of duplicates or orphaned runs. "Status says done" means done.
- **Variability**: Idempotency key eliminates nondeterminism from double-submission. Lease model eliminates nondeterminism from concurrent workers racing over the same run.
- **Maintenance cost**: Crash recovery is automatic (sweeper). Operators don't need to manually clean up stuck `running` runs.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes — the queue, lease, and idempotency primitives are packet-agnostic. They apply to any run type.

**Does it depend on a specific test packet?**

No. The queue/lease/idempotency logic is independent of packet content.

**Could this break other case types?**

No — this pass is purely additive to the execution harness. Pipeline logic and renderer are untouched.

**Does it introduce silent failure risk?**

Potential risk: if `mark_succeeded()` raises due to uncommitted artifacts, the run must not silently fall to `success` via another code path. Guard: the only call site for status promotion is `queue.py :: mark_succeeded()`.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

- "I uploaded the same case twice and got charged twice and got two different PDFs" → cancels immediately
- "The processing said done but there was no PDF" → cancels immediately

**Does this pass eliminate one of those risks?**

Yes — both. INV-Q2 (idempotency dedup) eliminates duplicate runs. INV-Q1 (artifact commit gate) eliminates "succeeded with no PDF."

---

## Prohibited Behaviors Check (govpreplan §10)

Confirm none of the following are introduced by this pass:

- [x] Silent fallback logic — mark_succeeded raises, does not silently succeed
- [x] Renderer inference (renderer computes anything) — renderer untouched
- [x] Non-deterministic ordering — queue is FIFO by created_at
- [x] Hidden policy defaults — no policy changes
- [x] Direct EvidenceGraph access from Trajectory — no trajectory changes
- [x] Fixing tests by hiding outputs instead of correcting logic — no existing tests modified
- [x] Policy changes without version increment — no policy changes

(All confirmed clean — none introduced.)

---

## Invariant Registry Update

- [ ] `governance/invariants.md` will be updated with INV-Q1 and INV-Q2
- [ ] No existing invariant is silently removed or weakened

---

## Checklist Summary

| Section | Status | Note |
|---|---|---|
| 1 System State | ✅ | Pilot readiness stage; additive only |
| 2 Failure Class | ✅ | Trust erosion (primary), coupling (secondary) |
| 3 Failure Defined | ✅ | Missing idempotency_key, lock columns, write_state |
| 4 Binary Success | ✅ | 3 binary must-be-impossible + 3 must-be-guaranteed |
| 5 Arch Move | ✅ | Formal state machine: queue + claim + artifact barrier |
| 6 Invariants | ✅ | INV-Q1 (artifact gate) + INV-Q2 (idempotency dedup) + INV-Q3 (registry centralized) |
| 7 Tests | ✅ | 6 unit + 2 integration = 8 total |
| 8 Risk Reduced | ✅ | Legal, trust, variability, maintenance |
| 9 Overfitting | ✅ | Packet-agnostic, no case-type assumptions |
| 10 Cancellation | ✅ | Eliminates both cancellation-class failures |
| Prohibited Behaviors | ✅ | All clear |
| Registry Update | ☐ | governance/invariants.md updated at implementation time |

Checklist is complete and internally consistent.
Implementation plan is in plan.md.
