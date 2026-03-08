# Pass 117 Plan

## Goal

Remove the Vercel upload-body bottleneck by moving document transport to direct storage upload while keeping backend validation and document registration authoritative.

## Recommended Rollout

1. Add backend upload-init and upload-complete endpoints.
2. Implement direct upload against the existing Supabase `documents` bucket.
3. Switch the production frontend upload flow to:
   - request upload intent
   - upload file directly to storage
   - confirm completion with backend
4. Keep a temporary fallback for legacy/small-file upload only if needed for rollout safety.
5. Validate end-to-end with a real cloud smoke upload, including a packet that exceeds the current Vercel proxy limit.

## Backend Work

### New contract

- `POST /matters/{matter_id}/documents/upload-init`
  - authenticate user/firm access
  - validate requested filename/content type/size
  - mint a short-lived upload intent
  - return:
    - storage bucket
    - object key
    - signed upload URL or signed headers/token
    - expiration
    - max size

- `POST /matters/{matter_id}/documents/upload-complete`
  - authenticate user/firm access
  - verify uploaded object exists
  - verify object key belongs to the upload intent
  - verify size <= configured limit
  - download enough bytes to confirm PDF signature
  - compute checksum or verify provided checksum against actual content
  - dedupe against existing `SourceDocument`
  - create `SourceDocument`
  - persist `storage_uri`

### Shared storage changes

- Extend `packages/shared/storage.py` with direct-upload helpers for Supabase:
  - generate object key
  - generate signed upload target if supported
  - verify object metadata
  - optionally move from staging key to canonical key

### Data model

- Prefer no DB migration if upload intents can remain stateless/signed.
- If server-tracked intents are needed, add a small upload-intent table only if necessary.

## Frontend Work

### Production UI

- Replace multipart proxy upload in:
  - `C:\eventis\website\app\api\citeline\matters\[matterId]\documents\route.ts`
  - `C:\eventis\website\app\app\new-case\page.tsx`
  - `C:\eventis\website\app\app\cases\[caseId]\page.tsx`
- New flow:
  - call upload-init
  - upload file directly from browser to Supabase
  - call upload-complete
  - surface progress/errors clearly

### Proxy route role

- Either:
  - retire the file-body proxy entirely, or
  - reduce it to lightweight session/auth orchestration without carrying file bytes

## Security Rules

- Upload target must be scoped to:
  - firm
  - matter
  - one object key
  - one content type
  - max size
  - short expiry
- Backend must fail closed if:
  - object missing
  - key mismatch
  - file not a PDF
  - size exceeds limit
  - hash mismatch

## Testing

- Backend unit/integration tests for upload-init/upload-complete
- Frontend contract test for the new upload flow
- Real cloud smoke test:
  - one small normal PDF
  - one large scan-heavy PDF that currently exceeds the Vercel proxy threshold

## Out of Scope

- packet generator changes
- worker extraction changes
- artifact/renderer changes
- switching to a new storage vendor unless Supabase proves insufficient

## Expected Outcome

- Realistic large packets are no longer blocked by the web proxy
- Upload limits are owned by CiteLine backend policy and storage capability
- Existing worker/storage contract remains intact after registration
