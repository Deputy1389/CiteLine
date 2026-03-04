# Pass 048 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`

---

## PASS TITLE

**Pass 048 - Phase 1 API Idempotency (`POST /v1/jobs`)**

---

## 1. System State

**Stage**: Hardening -> early productization

**Signal layer status**: stable/canonical

**Leverage/API layer status**: `/v1/jobs` facade live; idempotent create not yet implemented

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

Idempotent create is a contract-stability guard for integrators and prevents duplicate runs from retries without changing extraction logic.

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [ ] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [x] Architectural coupling / layer bleed

**Which one is primary?**

Architectural coupling / layer bleed

**Optional secondary (only if tightly related):**

Trust erosion risk

**Why is this the highest risk right now?**

Without idempotency, client retries can create duplicate runs and divergent downstream behavior across integration channels.

---

## 3. Define the Failure Precisely

**What test fails today?**

No API test proves that repeated `POST /v1/jobs` with identical idempotency key reuses the same job.

**What artifact proves the issue?**

Current `jobs_v1.py` create handler always inserts a new run.

**Is this reproducible across packets?**

Yes.

**Is this systemic or packet-specific?**

Systemic.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- Replaying the same client create request with the same idempotency key should not create another run.

**Must be guaranteed:**

- Same idempotency key + same request payload returns the same `job_id`.
- Same idempotency key + different payload returns `409`.

**Must pass deterministically:**

- API integration tests prove stable response mapping for replayed requests.

---

## 5. Architectural Move (Not Patch)

This pass is:

- [x] Adding boundary enforcement?
- [x] Introducing a guard pattern?
- [x] Consolidating logic?
- [ ] Eliminating duplication?
- [x] Separating layers more cleanly?

**Describe the move:**

Move create dedup responsibility into the `/v1/jobs` boundary contract using the existing `runs.idempotency_key` persistence field.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-API-03

**Name**: V1_JOB_CREATE_IDEMPOTENT

**What must always be true after this pass?**

For `/v1/jobs`, identical `(matter_id, Idempotency-Key)` with matching payload returns the original run and does not create duplicates.

**Where is it enforced?**

`apps/api/routes/jobs_v1.py` create handler.

**Where is it tested?**

`tests/integration/test_api_v1_jobs.py`.

**What is added to `governance/invariants.md`?**

Deferred to governance update pass.

---

## 7. Tests Added

**Unit tests:**

- None.

**Integration tests:**

- Replay with same idempotency key returns same `job_id`.
- Replay with same idempotency key but different payload returns `409`.

**Determinism comparison (if applicable):**

- Not applicable.

**Artifact-level assertion (if applicable):**

- Not applicable.

**Total new tests:** 2 (planned)

---

## 8. Risk Reduced

This pass reduces which risks:

- [ ] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

Idempotent create eliminates duplicate-run drift from client retries and reduces operational cleanup and incident triage.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes.

**Does it depend on a specific test packet?**

No.

**Could this break other case types?**

No case-type logic involved.

**Does it introduce silent failure risk?**

No; mismatched replay returns explicit `409`.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- Duplicate jobs from transient client retries.
- Inconsistent API run counts and status confusion.

**Does this pass eliminate one of those risks?**

Yes.

---

## Prohibited Behaviors Check

Confirm none are introduced:

- [x] Silent fallback logic
- [x] Renderer inference (renderer computes anything)
- [x] Non-deterministic ordering
- [x] Hidden policy defaults
- [x] Direct EvidenceGraph access from Trajectory
- [x] Fixing tests by hiding outputs instead of correcting logic
- [x] Policy changes without version increment

