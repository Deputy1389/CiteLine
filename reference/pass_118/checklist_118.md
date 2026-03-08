# Pass 118 Checklist

## PHASE 1 - DIAGNOSE (Before proposing anything)

### 0a. System Model

- Major components involved
  - Direct upload contract in `apps/api/routes/documents.py`
  - Shared storage helpers in `packages/shared/storage.py`
  - Existing `SourceDocument` DB registration path
- Data flow through those components
  - browser uploads directly to Supabase using a signed URL
  - backend `upload-complete` downloads the object, validates it, dedupes it, and optionally creates `SourceDocument`
- Ownership of state
  - storage owns the raw uploaded blob
  - backend owns acceptance/rejection and document registration
  - DB owns the canonical list of registered documents
- Boundaries between layers
  - browser -> storage
  - backend -> storage verification
  - backend -> DB registration

Weakest architectural boundary:
- Rejected or deduped upload objects can remain in storage even though the backend decided they are not valid registered documents.

### 0b. Failure Mode Analysis

1. Invalid uploaded object remains in storage after backend rejection.
   - Severity: Medium
   - Probability: Medium
   - Detectability: Low
   - Blast radius: storage bloat, debugging confusion
2. Duplicate-content upload remains in storage after dedupe reuses an existing document.
   - Severity: Medium
   - Probability: High
   - Detectability: Low
   - Blast radius: unnecessary storage growth
3. Cleanup deletes the wrong object key.
   - Severity: High
   - Probability: Low
   - Detectability: Medium
   - Blast radius: data loss
4. Cleanup failure masks the original validation failure.
   - Severity: Medium
   - Probability: Medium
   - Detectability: Medium
   - Blast radius: poor supportability
5. Local mirror files linger after failed registration.
   - Severity: Low
   - Probability: Low
   - Detectability: Low
   - Blast radius: disk bloat

Highest-risk failure class:
- Maintenance cost from orphaned uploaded objects that are not represented by any `SourceDocument`.

### 0c. Architectural Smell Detection

- Hidden state
  - storage can contain objects that are not valid system documents
- Unclear ownership
  - backend rejects the upload logically, but storage still retains it physically
- Silent fallbacks masking real errors
  - dedupe success can hide that a brand-new uploaded blob was never cleaned up

### 0d. Dangerous Illusion Check

- The dangerous illusion is that a rejected upload is "gone" once the API returns an error or reuses an existing document. In reality, the raw object can still exist in storage and silently accumulate.

## PHASE 2 - DESIGN (The pass proposal)

### PASS TITLE:

Direct Upload Orphan Cleanup

### 1. System State

- Stage: hardening after architectural rollout
- Are we allowed to add features this pass? No
- Why:
  - this is boundary cleanup for the direct-upload path, not new functionality

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

Why this is highest risk now:
- The upload contract is in place. The next risk is storage state diverging from the backend’s accepted document state.

### 3. Define the Failure Precisely

What test fails today?
- Rejected or deduped direct uploads can leave remote objects behind with no `SourceDocument`.

What artifact proves the issue?
- `reference/pass_117/summary.md`

Is this reproducible across packets?
- Yes, for any direct upload that is invalid or duplicates existing content.

Is this systemic or packet-specific?
- Systemic to the direct-upload rejection path.

### 4. Define the Binary Success State

After this pass:
- A direct-upload object rejected by backend validation is best-effort deleted from storage.
- A duplicate-content direct-upload object is best-effort deleted from storage when an existing document is reused.
- Cleanup failures do not mask the original business outcome.

Binary success criteria:
- "Invalid or deduped direct-upload objects trigger cleanup of their storage key before the API returns."

### 5. Architectural Move (Not Patch)

- Adding boundary enforcement
- Consolidating object lifecycle ownership in the backend

Why this is architectural:
- It aligns physical storage lifecycle with logical document acceptance instead of letting storage accumulate objects the application has already rejected.

### 6. Invariant Introduced

What invariant must always be true after this pass?
- A direct-upload object that is not accepted as a new `SourceDocument` should not remain in the canonical documents bucket unless cleanup itself fails.

Where enforced?
- `upload-complete` rejection and dedupe paths
- storage delete helper

Where tested?
- backend integration tests

### 7. Tests Planned

- Integration tests
  - duplicate upload triggers cleanup call
  - invalid content triggers cleanup call
- Regression tests
  - accepted direct upload still registers successfully

### 8. Risk Reduced

- [ ] Legal risk
- [ ] Trust risk
- [ ] Variability
- [x] Maintenance cost
- [ ] Manual review time

Explain how.
- It prevents silent storage drift and reduces long-term cleanup/debugging burden.

### 9. Overfitting Check

Is this solution generalizable?
- Yes, it applies to all direct-upload rejections.

Does it depend on a specific packet?
- No.

Could this break other case types or buckets?
- No, it is document-agnostic.

Does it introduce silent failure risk?
- Only if cleanup exceptions override the primary response; the pass must avoid that.

### 10. Cancellation Test

If a $1k/month PI firm used this system:
- they would not cancel over an internal orphan blob directly
- but teams would cancel if the system became unreliable or expensive due to upload architecture sloppiness

Does this pass eliminate one of those risks?
- It removes a real maintainability flaw in the new upload path.

## PHASE 3 - HARDEN (After implementation, before closing)

### 11. Adversarial QA

Verified:
- cleanup on duplicate content
- cleanup on invalid PDF signature
- cleanup does not run on accepted uploads

Known residual:
- abandoned uploads that never call `upload-complete` are still out of scope for this pass

### 12. Determinism Audit

Sources of nondeterminism:
- storage delete success/failure

Determinism rule:
- acceptance/rejection outcome must not depend on cleanup success

Observed:
- duplicate-content resolution remains deterministic
- cleanup is best-effort and does not alter the primary acceptance decision

### 13. Test Coverage Gap Analysis

Still likely missing after implementation:
- cleanup on missing-object path
- cleanup on DB write failure after local mirror save
- abandoned upload sweep for never-completed uploads

## PHASE 4 - SIMPLIFY (Before closing the pass)

### 14. Complexity Reduction

- Keep cleanup helper small and bucket-specific
- Avoid introducing background jobs in this pass

### 15. Senior Engineer Review

Potential block reasons:
- cleanup deleting canonical accepted objects
- cleanup exceptions changing the user-visible outcome

Current answer:
- cleanup is limited to the direct-upload object key carried in the signed intent
- accepted uploads do not trigger cleanup
- cleanup is best-effort and cannot override the main response path

### 16. Production Readiness Audit

At scale:
- best-effort cleanup at rejection time is cheap
- abandoned uploads that never call `upload-complete` still need a later sweep strategy, but that is out of scope here

Current readiness:
- deterministic orphan cases are handled
- long-tail abandoned-upload cleanup still needs a future pass

## Pass-Specific Constraints

- No DB migration
- No worker changes
- Cleanup must be best-effort and must not override the primary validation result
