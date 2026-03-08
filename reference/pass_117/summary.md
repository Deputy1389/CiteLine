# Pass 117 Summary

Pass 117 implemented the direct-to-storage upload contract to remove the Vercel file-body bottleneck from the medical-record upload path.

What changed:
- backend now exposes `upload-init` and `upload-complete` in [documents.py](C:/Citeline/apps/api/routes/documents.py)
- shared Supabase helpers in [storage.py](C:/Citeline/packages/shared/storage.py) now create signed upload URLs and verify uploaded objects
- production website now uploads file bytes directly from the browser, using the new routes in:
  - [upload-init route](C:/eventis/website/app/api/citeline/matters/[matterId]/documents/upload-init/route.ts)
  - [upload-complete route](C:/eventis/website/app/api/citeline/matters/[matterId]/documents/upload-complete/route.ts)
  - [document-upload helper](C:/eventis/website/lib/document-upload.ts)
- the case creation and case detail upload flows now use the direct-upload helper instead of proxying multipart file bodies through the website server

Key architectural outcome:
- the website no longer needs to carry the PDF body through its server route for the main upload flow
- backend still owns authorization, PDF validation, dedupe, and `SourceDocument` creation
- worker/download compatibility is preserved by uploading to the canonical `documents/{document_id}.pdf` storage key from the start

Verification:
- `python -m pytest tests/integration/test_api_direct_upload.py tests/integration/test_api_lists.py -q` -> `4 passed`
- `npx tsc --noEmit` in `C:\eventis\website` -> passed

Brutally honest:
- the architecture change is implemented
- local contract verification is green
- I did not run a deployed production smoke upload on `www.linecite.com` after this change, so the final proof that the live Vercel bottleneck is removed still depends on deploy + smoke
- orphan cleanup for abandoned or deduped uploads is still a follow-up item
