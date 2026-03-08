# Pass 117 Checklist

## PHASE 1 - DIAGNOSE (Before proposing anything)

### 0a. System Model

Describe the current architecture relevant to this pass:

- Major components involved
  - Production web upload entrypoint: `C:\eventis\website\app\api\citeline\matters\[matterId]\documents\route.ts`
  - Backend upload endpoint: `apps/api/routes/documents.py`
  - Shared storage helpers: `packages/shared/storage.py`
  - Worker consumption path: `packages.shared.storage.get_upload_path()` and pipeline document loading
- Data flow through those components
  - Browser uploads PDF to `www.linecite.com`
  - Next.js route reads `request.formData()`
  - Next.js route re-posts multipart body to backend `/matters/{matter_id}/documents`
  - Backend reads full file into memory, validates PDF/hash, saves to local disk and Supabase storage, creates `SourceDocument`
  - Worker later reads the upload from local disk or Supabase storage
- Ownership of state
  - Frontend route currently owns transport/proxying but should not own file transport policy
  - Backend owns authorization, validation, dedupe, and `SourceDocument` creation
  - Shared storage owns file persistence
- Boundaries between layers
  - browser -> Next.js proxy
  - Next.js proxy -> backend API
  - backend API -> storage
  - backend API -> DB
  - worker -> storage

Identify the weakest architectural boundary.

- The weakest boundary is the Next.js proxy route because it handles large binary transport even though the backend and storage layers already own validation and persistence. That creates an infrastructure-imposed size limit before CiteLine business logic runs.

### 0b. Failure Mode Analysis

List the top 5-10 ways the relevant subsystem could fail in production.

1. Large PDFs are rejected at the web edge before backend validation.
   - Severity: High
   - Probability: High
   - Detectability: High
   - Blast radius: firms cannot upload real productions
2. Direct upload tokens are over-scoped and allow writing to arbitrary keys.
   - Severity: High
   - Probability: Medium
   - Detectability: Medium
   - Blast radius: security breach / cross-matter contamination
3. Upload completes to storage but backend registration fails, leaving orphaned blobs.
   - Severity: Medium
   - Probability: Medium
   - Detectability: Medium
   - Blast radius: storage bloat / confusing UX
4. Backend trusts client metadata instead of verifying object content.
   - Severity: High
   - Probability: Medium
   - Detectability: Low
   - Blast radius: invalid or hostile content enters pipeline
5. Dedupe logic diverges between direct-upload and legacy upload paths.
   - Severity: Medium
   - Probability: Medium
   - Detectability: Medium
   - Blast radius: duplicate source docs / inconsistent behavior
6. Frontend upload UX regresses for small files.
   - Severity: Medium
   - Probability: Medium
   - Detectability: High
   - Blast radius: higher support burden
7. Worker cannot resolve newly-registered storage keys.
   - Severity: High
   - Probability: Low
   - Detectability: High
   - Blast radius: runs fail after apparently successful upload
8. Production secrets/config are incomplete for signed upload flow.
   - Severity: High
   - Probability: Medium
   - Detectability: High
   - Blast radius: rollout blocked

Identify the single highest-risk failure class.

- Trust erosion risk from real client packets being rejected before processing because the upload architecture is wrong for litigation-scale PDFs.

### 0c. Architectural Smell Detection

Identify any of these smells in the area being changed:

- Layer bleed
  - The web proxy currently owns binary transport even though file persistence already belongs to storage/backend.
- Duplicated logic
  - Upload validation/persistence exists in backend, but proxy forwarding duplicates transport work unnecessarily.
- Hidden state
  - Effective upload limit is not the backend `MAX_UPLOAD_BYTES`; it is the smaller Vercel function payload cap.
- Unclear ownership
  - The system appears to support `25 MB` uploads in backend code, but production behavior is controlled by the web edge.
- Policy embedded in infrastructure
  - Upload acceptance is being decided by serverless request limits instead of CiteLine validation policy.
- Silent fallbacks masking real errors
  - Users see upload failure without clear distinction between platform body cap vs backend document validation.

### 0d. Dangerous Illusion Check

Answer this question:

> What is the most dangerous illusion this system currently creates?
> Where could it appear correct while actually being wrong?

- The most dangerous illusion is that CiteLine supports large record uploads because the backend route advertises a `25 MB` limit and storage is already wired. In production that is false: the upload can fail earlier at the Next/Vercel proxy, so the system looks architecturally ready while actually rejecting realistic litigation packets.

## PHASE 2 - DESIGN (The pass proposal)

### PASS TITLE:

Direct-to-Storage Upload Architecture

### 1. System State

Which stage are we in?

- Architecture hardening for litigation-scale packet ingestion.

Are we allowed to add features this pass? (Yes/No)

- Yes.

If yes, why is that safer than further hardening?

- Because the missing capability is architectural, not cosmetic. Hardening the existing proxy path cannot remove the Vercel body limit. A new direct-upload contract is the safer move because it aligns transport with the existing storage model instead of layering more patches onto a failing boundary.

### 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [x] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

Which one is primary?

- Trust erosion risk

Optional: identify one secondary risk only if tightly related.

- Architectural coupling / layer bleed

Explain why this is highest risk right now.

- Firms cannot trust a litigation document system that rejects realistic productions at upload time. This is earlier and more fatal than any extraction bug because the case never enters the pipeline.

### 3. Define the Failure Precisely

What test fails today?

- A large image-heavy packet uploaded through the production web path fails before backend validation with `413 Request Entity Too Large / FUNCTION_PAYLOAD_TOO_LARGE`.

What artifact proves the issue?

- `reference/pass_116/cloud_batch/cloud_validation_summary.json`
- `reference/pass_116/summary.md`

Is this reproducible across packets?

- Yes, for sufficiently large PDFs routed through the current web proxy.

Is this systemic or packet-specific?

- Systemic. Packet size is the trigger, but the failure mechanism is architectural.

### 4. Define the Binary Success State

After this pass:

What must be impossible?

- Large-file acceptance must no longer depend on the Vercel request body limit.

What must be guaranteed?

- Backend remains the authority for auth, validation, dedupe, and `SourceDocument` registration.

What must pass deterministically?

- Upload initiation, upload completion registration, and worker retrieval must behave identically for direct-upload and legacy-compatible documents.

Write success criteria in binary form.

- "A browser upload can place a PDF into storage and register a `SourceDocument` without proxying the file body through the Next.js upload route."
- "The backend rejects invalid or oversized uploads based on CiteLine policy, not Vercel payload limits."
- "A registered direct-upload document is downloadable and processable by the existing worker path."

### 5. Architectural Move (Not Patch)

Is this pass:

- [x] Adding boundary enforcement
- [x] Introducing a guard pattern
- [x] Consolidating logic
- [ ] Eliminating duplication
- [x] Separating layers more cleanly

Explain why this is an architectural fix and not a patch.

- It changes the upload contract so storage handles binary transport, backend handles policy and registration, and the web app stops acting as a file relay. That removes the wrong boundary entirely instead of trying to patch around its limits.

### 6. Invariant Introduced

What invariant must always be true after this pass?

- Upload bytes reach storage directly, and no document becomes a `SourceDocument` until backend validation confirms the uploaded object belongs to the requesting firm/matter and satisfies size/type/hash rules.

Where is it enforced?

- New backend upload-init and upload-complete endpoints
- frontend upload flow
- shared storage helpers

Where is it tested?

- backend integration tests
- frontend/API contract tests
- cloud smoke validation

### 7. Tests Planned

Specify exact tests:

- Unit tests
  - storage key generation and request validation
  - upload-complete verification paths
- Integration tests
  - upload-init returns scoped target metadata
  - upload-complete creates `SourceDocument` only after object verification
  - duplicate upload reuses existing document when checksum matches
- Regression tests
  - existing small-file upload path still works during rollout if retained
  - document download endpoint still resolves uploaded files
- Cloud smoke test
  - real upload through production frontend path using the new direct-upload flow

### 8. Risk Reduced

This pass reduces which risks:

- [ ] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Maintenance cost
- [ ] Manual review time

Explain how.

- It removes infrastructure-dependent upload rejection, makes limits explicit in backend policy, and reduces the mismatch between local/backend behavior and production behavior.

### 9. Overfitting Check

Is this solution generalizable?

- Yes. It applies to all uploaded PDFs, not just scan-heavy packets.

Does it depend on a specific packet?

- No.

Could this break other case types or buckets?

- Not if registration and worker contracts remain document-agnostic.

Does it introduce silent failure risk?

- It could if upload-complete validation is weak; the plan must make validation explicit and fail closed.

### 10. Cancellation Test

If a $1k/month PI firm used this system:

What would make them cancel?

- Rejection of the actual medical productions they need processed.

Does this pass eliminate one of those risks?

- Yes. It directly targets the upload-path rejection risk.

If not, reconsider the pass.

## PHASE 3 - HARDEN (After implementation, before closing)

### 11. Adversarial QA

- Implemented/focused checks:
  - direct-upload happy path
  - duplicate-content registration reuses the existing `SourceDocument`
  - non-PDF content is rejected at `upload-complete`
- Remaining adversarial checks not yet automated:
  - missing uploaded object
  - wrong-matter intent replay
  - expired upload intent
  - declared-size mismatch
  - orphan cleanup after dedupe

### 12. Determinism Audit

Identify all sources of nondeterminism introduced or exposed by this pass:

- signed upload expirations
- object storage eventual consistency
- client-side progress/retry timing
- upload session identifiers

For each source: is determinism enforced? How?

- Upload session IDs may vary, but registration outcome must be deterministic for the same stored object.
- Object verification must key off storage metadata and content hash, not request timing.
- Expiration affects authorization only, not document semantics.
- Verified in tests:
  - duplicate upload-complete calls with the same content resolve to the same existing document record instead of creating divergent duplicates.

### 13. Test Coverage Gap Analysis

Based on the changes made, what critical tests are still missing?

- Still missing:
  - failed upload cleanup / orphan handling
  - concurrent upload-complete calls for the same object
  - rollback behavior if DB write fails after object verification
  - deployed production smoke using the new website flow against `www.linecite.com`

## PHASE 4 - SIMPLIFY (Before closing the pass)

### 14. Complexity Reduction

Did this pass increase complexity? Where?

- It introduces an upload session/registration contract.

Show how to reduce:

- keep the contract to two endpoints: `upload-init` and `upload-complete`
- reuse existing storage buckets instead of introducing a second storage system
- keep worker retrieval unchanged by storing to the same `documents` bucket/key pattern where possible
- Actual simplification achieved:
  - no DB migration
  - no worker contract change
  - no new storage vendor
  - legacy multipart upload endpoint left intact for fallback/compatibility during rollout

### 15. Senior Engineer Review

Assume a staff engineer is reviewing this pass before release.

What would make them block it?

- broad or reusable upload credentials in the browser
- weak post-upload validation
- breaking existing download/worker assumptions
- rollout without fallback for small-file uploads
- unclear orphan cleanup strategy
- Current residual concerns:
  - upload intents are stateless and signed, which is good for rollout simplicity, but orphan cleanup still needs follow-up
  - direct-upload production smoke is still required before claiming the Vercel bottleneck is fully retired in prod

### 16. Production Readiness Audit

If this system handled 10,000 real cases with this change:

What would break?

- storage costs rise if orphaned uploads are not cleaned
- backend support burden rises if upload-complete errors are not diagnosable
- UX degrades if retries/progress are poor
- security risk rises if signed uploads are too permissive
- Current readiness state:
  - implementation complete locally
  - backend tests green
  - frontend typecheck green
  - production deployment and live smoke still pending

## Pass-Specific Constraints

- Reuse the existing Supabase-backed storage path if possible; do not introduce a new storage vendor unless forced.
- Preserve backend ownership of validation, dedupe, and `SourceDocument` creation.
- Keep worker download/read path compatible with existing storage keys unless a migration is explicitly planned.
