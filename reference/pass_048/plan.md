# Pass 048 - Plan

## Objective
Implement idempotent job creation behavior for `POST /v1/jobs` so client retries do not create duplicate runs.

## Scope
- Support `Idempotency-Key` request header on `POST /v1/jobs`.
- Persist/reuse `runs.idempotency_key` for v1 create flow.
- Return existing job for replayed identical request.
- Return `409` on replay with same key but different payload.
- Add integration tests for replay and mismatch behavior.

## Non-Scope
- Queue/orchestrator redesign.
- Webhook subsystem.
- Auth/tenant rollout changes.
- Legacy run route idempotency.

## Implementation Steps
1. Add header parsing and key validation to v1 create route.
2. Add deterministic key mapping helper for storage (`sha256`).
3. Lookup existing run by idempotency key before insert.
4. Insert with key for first request; handle key race safely.
5. Add integration tests for key replay and mismatch.
6. Run targeted integration tests.

## Acceptance Criteria
- Same `Idempotency-Key` + same request payload returns same `job_id`.
- Same `Idempotency-Key` + different payload returns `409`.
- Requests without key keep current create behavior.
- Existing v1 jobs tests remain passing.

## Risks and Mitigations
- Risk: collision with other idempotency usages.
  - Mitigation: namespaced key derivation in v1 route helper.
- Risk: concurrent create race.
  - Mitigation: rely on unique DB constraint and re-read on conflict.

## Deliverables
- `apps/api/routes/jobs_v1.py` updates.
- `tests/integration/test_api_v1_jobs.py` new tests.
- Pass artifacts in `reference/pass_048/`.
