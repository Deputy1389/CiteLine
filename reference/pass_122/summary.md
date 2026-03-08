# Pass 122 Summary

## Bug

The newly deployed direct-upload flow returned a malformed Supabase signed URL from `upload-init`.

Observed live failure before fix:

- `upload-init`: `200`
- browser upload to signed URL: `404 {"error":"requested path is invalid"}`
- `upload-complete`: `404 Uploaded object not found`

Root cause:

- `create_signed_upload_url()` concatenated `SUPABASE_REST_URL` with the provider-returned relative path directly.
- Supabase returned `/object/upload/sign/...`
- the resulting URL missed the required `/storage/v1` prefix

## Fix

- Added `_normalize_supabase_signed_url()` in [storage.py](C:/Citeline/packages/shared/storage.py)
- `create_signed_upload_url()` now returns a fully qualified working upload URL for:
  - absolute URLs
  - `/storage/v1/...` paths
  - `/object/...` paths

## Verification

Local tests:

- `python -m pytest tests/unit/test_storage_direct_upload.py tests/integration/test_api_direct_upload.py tests/integration/test_api_lists.py tests/unit/test_upload_orphan_sweeper.py -q`
- result: `12 passed`

Live production recheck after deploy `abd917f`:

1. Direct-upload handshake
   - `upload-init`: `200`
   - signed URL now includes `/storage/v1/object/upload/sign/...`
   - browser upload to Supabase: `200`
   - `upload-complete`: `201`

2. Full intake on enterprise-tier matter
   - Matter: `25223387ef5247a0b732c444fe4f180e`
   - Document: `f3fb6feecbe2401987845edd90faca83`
   - Run: `e6bcf29c0739480b9bd5a53938916c96`
   - Run start: `202`
   - Final status: `needs_review`

## Current Live State

- Backend commit [abd917f](C:/Citeline/reference/pass_122/summary.md) is live on Render
- `ENABLE_UPLOAD_ORPHAN_SWEEPER=true` is active
- [health/upload-sweeper](https://linecite-api.onrender.com/health/upload-sweeper) reports the sweeper running
- Direct browser-to-storage upload is working in production

## Honest Read

The deployment path is now materially better than before:

- large-file intake is no longer blocked by the old website proxy architecture in the backend contract
- the backend sweeper is live
- the direct-upload handshake is proven in production

The only browser-flow artifact that still looked bad during this session was the old `/app/new-case` smoke script timing out before redirect. Based on the later direct-upload proof, that timeout was not caused by the signed URL bug anymore; it was more likely tied to the page flow and firm-tier selection path rather than the storage handshake itself.
