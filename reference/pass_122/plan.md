# Pass 122 Plan

## Goal

Fix the malformed Supabase signed upload URL returned by `upload-init`, then redeploy and rerun the direct-upload smoke.

## Steps

1. Patch `packages/shared/storage.py`:
   - normalize Supabase signed URL responses to a fully qualified upload URL
2. Add tests:
   - signed URL normalization unit coverage
   - preserve existing direct-upload integration tests
3. Rerun focused tests
4. Commit and push backend fix
5. Let Render deploy the new backend commit
6. Rerun website direct-upload E2E smoke
7. Write pass summary with exact before/after behavior

## Success Criteria

- `upload-init` returns a usable signed upload URL
- direct upload to Supabase succeeds
- `upload-complete` returns `201`
- a run can be started from the uploaded document
