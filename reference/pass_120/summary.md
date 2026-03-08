# Pass 120 Summary

Pass 120 added a real periodic upload-orphan sweeper to the API process.

What changed:
- [upload_orphan_sweeper.py](C:/Citeline/apps/api/upload_orphan_sweeper.py) now provides:
  - env-gated enablement
  - configurable sweep interval
  - one-shot sweep runner
  - daemon thread startup
- [main.py](C:/Citeline/apps/api/main.py) now:
  - starts the sweeper thread on startup when `ENABLE_UPLOAD_ORPHAN_SWEEPER=true`
  - stops it on shutdown
  - exposes [health/upload-sweeper](C:/Citeline/apps/api/main.py) for visibility
- existing sweep logic in [documents.py](C:/Citeline/apps/api/routes/documents.py) continues to do the actual bounded cleanup work

Verification:
- `python -m pytest tests/unit/test_upload_orphan_sweeper.py tests/integration/test_api_direct_upload.py tests/integration/test_api_lists.py -q` -> `8 passed`
- `npx tsc --noEmit` in `C:\eventis\website` -> passed

Brutally honest:
- this is the recommended lightweight version of a dedicated sweeper
- it is disabled by default and safe to roll out gradually
- it is not a distributed scheduler with leader election, so multiple API instances can do duplicate low-cost cleanup work
- that is acceptable for now given the bounded sweep and low blast radius
