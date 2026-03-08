# Pass 122 Checklist

## PHASE 1 - DIAGNOSE

### 0a. System Model

- Components:
  - `packages/shared/storage.py` creates Supabase signed upload URLs.
  - `apps/api/routes/documents.py` exposes `upload-init` and `upload-complete`.
  - `eventis/website` calls `upload-init`, uploads bytes to the signed URL, then calls `upload-complete`.
- Data flow:
  - website -> `upload-init` -> signed URL -> browser uploads to Supabase -> `upload-complete` validates and registers document.
- Ownership:
  - Signed URL generation belongs to backend storage helper.
  - Browser only transports bytes.
  - Backend remains authority for document registration.

Weakest boundary:
- The backend-generated signed URL contract between CiteLine and Supabase.

### 0b. Failure Mode Analysis

1. Signed upload URL points at wrong path.
   - Severity: high
   - Probability: high
   - Detectability: high
   - Blast radius: all direct uploads fail
2. Browser upload succeeds but `upload-complete` cannot find object.
   - Severity: high
   - Probability: high
   - Detectability: high
   - Blast radius: case intake blocked
3. Helper overcorrects and breaks already-correct absolute URLs.
   - Severity: medium
   - Probability: medium
   - Detectability: high
   - Blast radius: direct upload only

Highest-risk failure class:
- Data integrity failure in the signed upload URL contract.

### 0c. Architectural Smell Detection

- Hidden assumption: Supabase response URL shape was assumed instead of normalized.
- Silent fallback risk: `upload-init` succeeds, creating the illusion that direct upload is working.

### 0d. Dangerous Illusion Check

Most dangerous illusion:
- `upload-init` returning `200` looks like success while the generated signed URL is malformed and guarantees the subsequent upload will fail.

## PHASE 2 - DESIGN

### PASS TITLE:

Pass 122 - Fix Direct Upload Signed URL Normalization

### 1. System State

- Stage: hardening a newly deployed feature
- Allowed to add features this pass: No

### 2. Failure Class Targeted

- [x] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [ ] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

Primary:
- Data integrity failure

### 3. Define the Failure Precisely

- Failing test today:
  - direct upload signed URL misses `/storage/v1`
  - browser upload returns `404 requested path is invalid`
  - `upload-complete` returns `404 Uploaded object not found`
- Artifact proving issue:
  - live smoke output from the direct-upload E2E check on 2026-03-08
- Reproducibility:
  - systemic across direct uploads until fixed

### 4. Define the Binary Success State

After this pass:
- `upload-init` must always return a valid Supabase upload URL.
- Browser upload to that URL must not fail because of path normalization.
- `upload-complete` must be able to find the uploaded object when the upload succeeded.

### 5. Architectural Move (Not Patch)

- Normalize the Supabase signed URL at the storage boundary so callers never need to know provider-specific path quirks.

### 6. Invariant Introduced

- Invariant:
  - `create_signed_upload_url()` returns a fully qualified working upload URL.
- Enforced:
  - `packages/shared/storage.py`
- Tested:
  - new unit/integration assertions

### 7. Tests Planned

- Unit test for signed URL normalization
- Existing integration direct-upload tests
- Live website direct-upload smoke rerun

### 8. Risk Reduced

- [ ] Legal risk
- [x] Trust risk
- [x] Variability
- [ ] Maintenance cost
- [x] Manual review time

### 9. Overfitting Check

- Generalizable: Yes
- Packet-specific: No
- Provider-specific: only in the storage helper normalization layer

### 10. Cancellation Test

- A PI firm cancels if case intake fails on upload.
- This pass directly removes that risk for large-file direct uploads.

## PHASE 3 - HARDEN

### 11. Adversarial QA

- Test absolute URL input
- Test `/storage/v1/...` relative input
- Test `/object/...` relative input

### 12. Determinism Audit

- No new nondeterminism introduced.
- Pure string normalization only.

### 13. Test Coverage Gap Analysis

- Remaining gap after local tests:
  - full production smoke must still be rerun after redeploy

## PHASE 4 - SIMPLIFY

### 14. Complexity Reduction

- Keep normalization in one helper.
- Do not duplicate provider-specific URL fixes in frontend or route handlers.

### 15. Senior Engineer Review

- Blocker would be spreading URL fixups across callers instead of centralizing them.

### 16. Production Readiness Audit

- At scale, only the boundary helper matters here; once normalized, behavior is constant per request.
