# Pass 119 Checklist

## PHASE 1 - DIAGNOSE (Before proposing anything)

### 0a. System Model

- Major components involved
  - Direct-upload contract in `apps/api/routes/documents.py`
  - Shared storage helpers in `packages/shared/storage.py`
  - `SourceDocument` persistence in the DB
- Data flow through those components
  - browser uploads directly to storage
  - some uploads never call `upload-complete`
  - later upload activity can opportunistically inspect old storage objects and compare them against registered `SourceDocument` rows
- Ownership of state
  - storage owns raw uploaded objects
  - backend owns accepted document registration
  - DB owns canonical documents
- Boundaries between layers
  - storage object existence
  - backend registration decision
  - DB canonical state

Weakest architectural boundary:
- Storage can contain stale direct-upload objects with no matching `SourceDocument`, and nothing was cleaning them once the client abandoned the flow before `upload-complete`.

### 0b. Failure Mode Analysis

1. Abandoned direct uploads remain in storage indefinitely.
   - Severity: Medium
   - Probability: High
   - Detectability: Low
   - Blast radius: storage growth, debugging noise
2. Sweep deletes a registered canonical document.
   - Severity: High
   - Probability: Low
   - Detectability: Medium
   - Blast radius: data loss
3. Sweep deletes a recent in-flight upload before the client completes it.
   - Severity: High
   - Probability: Low
   - Detectability: Medium
   - Blast radius: intermittent upload failures
4. Sweep work slows down `upload-init`.
   - Severity: Medium
   - Probability: Medium
   - Detectability: High
   - Blast radius: degraded UX
5. Sweep failure breaks normal upload-init.
   - Severity: Medium
   - Probability: Medium
   - Detectability: High
   - Blast radius: upload outage

Highest-risk failure class:
- Maintenance cost from stale direct-upload objects accumulating without any cleanup path.

### 0c. Architectural Smell Detection

- Hidden state
  - object storage can diverge from canonical DB state
- Unclear ownership
  - abandoned objects have no owner once the browser disappears
- Silent fallbacks masking real errors
  - uploads appear to fail/vanish client-side, but storage can keep the blob forever

### 0d. Dangerous Illusion Check

- The dangerous illusion is that a direct upload that never finished is harmless. In reality it can leave a persistent blob in storage even though the application has no registered document for it.

## PHASE 2 - DESIGN (The pass proposal)

### PASS TITLE:

Abandoned Direct Upload Sweep

### 1. System State

- Stage: upload hardening
- Are we allowed to add features this pass? No
- Why:
  - this is lifecycle cleanup for the upload contract, not a user-facing feature

### 2. Failure Class Targeted

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

Primary:
- Architectural coupling / layer bleed

Secondary:
- Maintenance cost

Explain why this is highest risk right now.
- The upload contract is now live locally. The remaining obvious lifecycle gap is stale storage state that no longer maps to any application document.

### 3. Define the Failure Precisely

What test fails today?
- There is no cleanup path for direct-upload objects that never reach `upload-complete`.

What artifact proves the issue?
- `reference/pass_118/summary.md`

Is this reproducible across packets?
- Yes, for any abandoned direct upload.

Is this systemic or packet-specific?
- Systemic to the upload lifecycle.

### 4. Define the Binary Success State

After this pass:
- Old canonical direct-upload objects with no matching `SourceDocument` are eligible for deletion.
- Recent uploads are preserved.
- Registered documents are preserved.
- Upload-init still succeeds even if sweep work fails.

Binary success criteria:
- "A bounded sweep deletes only stale unregistered direct-upload `*.pdf` objects and never blocks `upload-init`."

### 5. Architectural Move (Not Patch)

- Adding boundary enforcement
- Consolidating ownership of stale object lifecycle into the backend

Why this is architectural:
- It aligns storage state with canonical application state instead of leaving abandonment cleanup outside the system.

### 6. Invariant Introduced

What invariant must always be true after this pass?
- Stale direct-upload objects older than the grace window and missing a matching `SourceDocument` should be removable by the backend without affecting active or registered uploads.

Where is it enforced?
- bounded sweep helper
- opportunistic invocation from `upload-init`

Where is it tested?
- integration tests for stale vs fresh vs registered objects

### 7. Tests Planned

- Integration tests
  - stale unregistered object is deleted
  - fresh object is skipped
  - registered object is skipped
- Regression tests
  - accepted direct upload still works
  - website typecheck remains green

### 8. Risk Reduced

- [ ] Legal risk
- [ ] Trust risk
- [ ] Variability
- [x] Maintenance cost
- [ ] Manual review time

Explain how.
- It bounds storage drift from abandoned uploads and makes upload lifecycle ownership explicit.

### 9. Overfitting Check

Is this solution generalizable?
- Yes, it is document-type agnostic.

Does it depend on a specific packet?
- No.

Could this break other case types or buckets?
- Not if restricted to canonical direct-upload document keys in the `documents` bucket.

Does it introduce silent failure risk?
- Only if sweep deletion is overbroad; the pass must constrain by naming pattern, age threshold, and DB existence check.

### 10. Cancellation Test

If a $1k/month PI firm used this system:
- they would not directly see abandoned storage blobs
- but sloppy upload infrastructure eventually creates cost and reliability problems

Does this pass eliminate one of those risks?
- Yes, it closes the abandoned-upload cleanup gap.

## PHASE 3 - HARDEN (After implementation, before closing)

### 11. Adversarial QA

Verified:
- stale unregistered object is deleted
- fresh object is skipped
- registered object is skipped
- upload-init path is not blocked by sweep failure because sweep is best-effort

Known residual:
- cross-instance/global scheduling is still opportunistic, not guaranteed

### 12. Determinism Audit

Sources of nondeterminism:
- storage listing order
- per-process sweep cooldown timing

Determinism enforcement:
- sweep sorts oldest-first via storage list configuration
- deletion policy depends on object age, naming pattern, and DB presence
- upload acceptance does not depend on sweep success

### 13. Test Coverage Gap Analysis

Still missing:
- cleanup verification when storage list API fails
- very large bucket pagination behavior beyond the configured sweep limit

## PHASE 4 - SIMPLIFY (Before closing the pass)

### 14. Complexity Reduction

- No new DB table
- No background worker
- No scheduler service
- One bounded helper plus opportunistic invocation

### 15. Senior Engineer Review

Potential block reasons:
- deleting active uploads
- sweeping too much on every request
- tying upload success to sweep success

Current answer:
- age threshold prevents active-upload deletion
- cooldown and limit bound the work
- sweep failure is swallowed and cannot block upload-init

### 16. Production Readiness Audit

At scale:
- bounded sweep work is cheap
- cleanup is partial by design and may need a future scheduled job for stronger guarantees
- current design is appropriate as a first operational cleanup layer

## Pass-Specific Constraints

- No DB migration
- No worker change
- Sweep only the canonical `documents` bucket
- Sweep only `32hex.pdf` direct-upload keys
