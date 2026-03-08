# Pass 119 Plan

## Goal

Add a bounded backend sweep for abandoned direct-upload objects so stale unregistered PDFs do not accumulate indefinitely in the `documents` bucket.

## Approach

1. Add storage list helper for Supabase object listing.
2. Add a backend sweep helper that:
   - lists oldest objects in the `documents` bucket
   - filters to canonical `32hex.pdf` direct-upload keys
   - skips recent objects
   - skips keys with a matching `SourceDocument`
   - deletes stale unregistered objects
3. Call the sweep opportunistically from `upload-init` with a cooldown.
4. Keep sweep best-effort so upload-init never fails because cleanup had issues.
5. Add tests proving stale vs fresh vs registered behavior.

## Out of Scope

- background jobs / cron
- sweeping non-canonical storage paths
- changing worker behavior

## Expected Outcome

- abandoned direct-upload objects older than the grace window are gradually cleaned up during later upload activity
- active and registered uploads are preserved
