# Pass 047 - Plan

## Objective
Implement Phase 1 API-first facade endpoints under `/v1/jobs` with feature-flag gating while reusing current run orchestration and preserving status/artifact semantics.

## Scope
- Add versioned routes for:
  - `POST /v1/jobs`
  - `GET /v1/jobs/{job_id}`
  - `GET /v1/jobs/{job_id}/artifacts`
  - `POST /v1/jobs/{job_id}/cancel`
- Map responses to existing run records/artifacts.
- Keep existing API surface fully backward compatible.
- Add route tests validating lifecycle semantics.

## Non-Scope
- Worker pipeline refactor
- New queue/orchestrator infra
- Webhook subsystem
- Tenant auth/rate-limit rollout

## Implementation Steps
1. Inspect existing run and export routes/models for reusable create/get/artifact logic.
2. Add feature flag config for API v1 jobs facade.
3. Implement new route module and register router.
4. Add response mapping helpers for stable status/artifact payloads.
5. Add tests for create/get/artifacts/cancel behavior.
6. Run targeted tests and fix regressions.

## Acceptance Criteria
- `/v1/jobs` facade works when feature flag enabled.
- Existing routes remain unchanged.
- Status values preserve `pending|running|success|partial|failed|needs_review`.
- Artifact listing exposes existing artifacts for a run.
- Test suite for new endpoints passes.

## Risks and Mitigations
- Risk: status mapping drift.
  - Mitigation: central mapping helper + tests for each status.
- Risk: breaking existing clients.
  - Mitigation: additive routes, feature flag default off.
- Risk: artifact contract mismatch.
  - Mitigation: reuse existing artifact serialization path where possible.

## Deliverables
- New/updated route files under `apps/api/routes`.
- Config flag wiring.
- Tests under `apps/api/tests`.
- Pass artifacts in `reference/pass_047/`.
