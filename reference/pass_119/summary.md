# Pass 119 Summary

Pass 119 added a bounded opportunistic sweep for abandoned direct-upload objects.

What changed:
- [storage.py](C:/Citeline/packages/shared/storage.py) now supports listing objects in the Supabase `documents` bucket
- [documents.py](C:/Citeline/apps/api/routes/documents.py) now includes a stale-object sweep that:
  - scans old `32hex.pdf` direct-upload keys
  - skips fresh uploads
  - skips keys backed by a `SourceDocument`
  - deletes stale unregistered objects
- the sweep is invoked opportunistically from `upload-init` behind a cooldown and age threshold so it does not block normal uploads

Verification:
- `python -m pytest tests/integration/test_api_direct_upload.py tests/integration/test_api_lists.py -q` -> `5 passed`
- `npx tsc --noEmit` in `C:\eventis\website` -> passed

Brutally honest:
- this closes the abandoned-upload gap in a practical first way
- it is not a guaranteed scheduler; it is a bounded cleanup pass piggybacking on later upload traffic
- if you want hard guarantees for zero long-lived abandoned objects, the next step would be a dedicated periodic sweeper
