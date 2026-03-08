# Pass 120 Plan

## Goal

Add a simple periodic daemon sweeper for abandoned direct-upload objects, gated by env and isolated from request handling.

## Approach

1. Add a dedicated sweeper module under `apps/api/`.
2. Reuse `documents.sweep_orphaned_direct_uploads()` and `packages.db.database.get_session()`.
3. Start a daemon thread on API startup only when `ENABLE_UPLOAD_ORPHAN_SWEEPER=true`.
4. Make the interval configurable with `UPLOAD_ORPHAN_SWEEP_INTERVAL_SECONDS`.
5. Add focused tests for:
   - one-shot sweep execution
   - enable/disable guard behavior

## Out of Scope

- distributed leader election
- cron/external scheduler
- new DB tables

## Expected Outcome

- abandoned-upload cleanup runs periodically when enabled, even during low user traffic
