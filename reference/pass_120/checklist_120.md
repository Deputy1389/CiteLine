# Pass 120 Checklist

## PHASE 1 - DIAGNOSE (Before proposing anything)

### 0a. System Model

- Major components involved
  - opportunistic sweep in `apps/api/routes/documents.py`
  - API startup lifecycle in `apps/api/main.py`
  - shared DB session management in `packages/db/database.py`
- Data flow through those components
  - direct uploads create storage objects
  - opportunistic sweeps only run during later upload-init traffic
  - during low/no upload traffic, stale objects may remain forever
- Ownership of state
  - backend owns cleanup policy
  - API process is the only always-on component in the current web path that can host a simple periodic sweep
- Boundaries between layers
  - storage cleanup logic
  - scheduler/trigger
  - API runtime lifecycle

Weakest architectural boundary:
- Cleanup currently depends on future user upload traffic. There is no guaranteed periodic trigger.

### 0b. Failure Mode Analysis

1. No user traffic means no orphan cleanup.
   - Severity: Medium
   - Probability: High
   - Detectability: Low
   - Blast radius: stale blobs accumulate indefinitely
2. Background sweeper thread crashes silently.
   - Severity: Medium
   - Probability: Medium
   - Detectability: Medium
   - Blast radius: cleanup silently stops
3. Sweeper blocks API startup or request handling.
   - Severity: High
   - Probability: Low
   - Detectability: High
   - Blast radius: availability incident
4. Multiple API instances run the sweep concurrently.
   - Severity: Low
   - Probability: Medium
   - Detectability: Low
   - Blast radius: duplicate cleanup work
5. Sweeper deletes active uploads due to bad timing/age threshold.
   - Severity: High
   - Probability: Low
   - Detectability: Medium
   - Blast radius: upload failures

Highest-risk failure class:
- Maintenance cost from having no guaranteed trigger for abandoned-upload cleanup.

### 0c. Architectural Smell Detection

- Hidden state
  - cleanup effectiveness depends on traffic patterns, not system policy
- Unclear ownership
  - abandoned-object lifecycle is only partially owned by the backend
- Silent fallbacks masking real errors
  - opportunistic cleanup makes the system look self-healing even when traffic is too low for it to run

### 0d. Dangerous Illusion Check

- The dangerous illusion is that abandoned uploads are "handled" because a sweep exists. Without a guaranteed periodic trigger, that is only conditionally true.

## PHASE 2 - DESIGN (The pass proposal)

### PASS TITLE:

Periodic Upload Orphan Sweeper

### 1. System State

- Stage: operational hardening
- Are we allowed to add features this pass? No
- Why:
  - this is operational triggering for existing cleanup logic, not new user-facing behavior

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
- The cleanup logic exists, but its trigger is still coupled to user traffic rather than system policy.

### 3. Define the Failure Precisely

What test fails today?
- There is no guaranteed periodic execution path for abandoned-upload cleanup.

What artifact proves the issue?
- `reference/pass_119/summary.md`

Is this reproducible across packets?
- Yes.

Is this systemic or packet-specific?
- Systemic.

### 4. Define the Binary Success State

After this pass:
- The API can run orphan cleanup periodically without waiting for user uploads.
- The sweeper is disabled by default unless explicitly enabled.
- Sweep failures do not crash the API process.

Binary success criteria:
- "When enabled by env, the API starts a daemon sweeper loop that periodically runs orphan cleanup without blocking startup or requests."

### 5. Architectural Move (Not Patch)

- Adding boundary enforcement
- Separating cleanup triggering from user traffic

Why this is architectural:
- It moves cleanup triggering into an explicit runtime policy instead of incidental request flow.

### 6. Invariant Introduced

What invariant must always be true after this pass?
- If the periodic sweeper is enabled, abandoned-upload cleanup will run on a fixed interval independent of upload traffic.

Where is it enforced?
- dedicated sweeper module
- API startup wiring

Where is it tested?
- unit tests for one-shot sweep runner and thread-start guard

### 7. Tests Planned

- Unit tests
  - one-shot sweeper uses DB session and calls cleanup
  - startup helper respects env enablement
- Regression tests
  - existing upload tests remain green

### 8. Risk Reduced

- [ ] Legal risk
- [ ] Trust risk
- [ ] Variability
- [x] Maintenance cost
- [ ] Manual review time

Explain how.
- It removes traffic dependence from cleanup and gives operations a predictable cleanup mechanism.

### 9. Overfitting Check

Is this solution generalizable?
- Yes, it is tied to the upload lifecycle, not any packet type.

Does it depend on a specific packet?
- No.

Could this break other case types or buckets?
- Not if restricted to the existing direct-upload cleanup helper.

Does it introduce silent failure risk?
- Only if thread failures are swallowed without logging; implementation must log failures and stay isolated from request handling.

### 10. Cancellation Test

If a $1k/month PI firm used this system:
- they would not directly care about the sweeper
- but they would care if operational sloppiness turned into cost or reliability issues

Does this pass eliminate one of those risks?
- Yes, it makes cleanup guaranteed when enabled.

## PHASE 3 - HARDEN (After implementation, before closing)

### 11. Adversarial QA

Verified:
- disabled by default
- one-shot sweep runner is independently testable
- startup helper respects env enablement
- request correctness does not depend on the sweeper thread

Known residual:
- no leader election across multiple API instances

### 12. Determinism Audit

Sources of nondeterminism:
- thread scheduling
- sweep interval timing
- multiple process instances

Determinism rule:
- cleanup cadence may vary slightly, but enabling the sweeper must not change request correctness

Observed:
- thread timing is nondeterministic by design
- sweep outcomes remain bounded by the same stale-object policy used in the one-shot helper
- request/registration behavior is unchanged whether the sweeper runs or not

### 13. Test Coverage Gap Analysis

Still likely missing after implementation:
- multi-instance deployment behavior
- production log visibility for sweep outcomes
- deployed smoke with `ENABLE_UPLOAD_ORPHAN_SWEEPER=true`

## PHASE 4 - SIMPLIFY (Before closing the pass)

### 14. Complexity Reduction

- Reuse existing sweep helper
- Reuse existing API startup background-thread pattern
- Keep daemon/env-gated

### 15. Senior Engineer Review

Potential block reasons:
- background thread started unconditionally
- thread can crash startup
- request path accidentally depends on sweep thread

Current answer:
- thread is env-gated
- startup catches sweeper startup errors and logs them
- sweeper is fully out-of-band from request handling

### 16. Production Readiness Audit

At scale:
- per-instance sweeper duplication is acceptable for this low-volume cleanup task
- a later central cron may still be cleaner, but this is sufficient and fast to ship

Current readiness:
- implementation complete locally
- tests green
- production behavior still depends on enabling the env flag during deploy

## Pass-Specific Constraints

- No worker changes
- Disabled by default
- Must not block startup or request handling
