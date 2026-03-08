# Pass 118 Plan

## Goal

Clean up orphaned direct-upload objects at deterministic backend rejection points without changing the accepted-upload contract.

## Scope

Implement best-effort cleanup for:
- duplicate-content direct uploads
- invalid direct uploads rejected during `upload-complete`

Out of scope:
- sweeping uploads that never call `upload-complete`
- new background jobs
- storage vendor changes

## Changes

1. Add object delete helpers to `packages/shared/storage.py`.
2. Add a backend cleanup helper in `apps/api/routes/documents.py`.
3. Call cleanup before returning on:
   - duplicate-content reuse
   - invalid content/signature/size mismatch/object-path mismatch
4. Keep cleanup failures non-fatal to the main API response.
5. Add integration tests proving cleanup is invoked on duplicate and invalid uploads.

## Expected Outcome

- The direct-upload path stops leaking obvious orphan objects when backend validation rejects or dedupes an upload.
