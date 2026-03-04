# Pass 049 - Plan

## Objective
Add webhook endpoint registry APIs for Phase 1 pivot under `/v1/webhooks/endpoints`.

## Scope
- `POST /v1/webhooks/endpoints`
- `GET /v1/webhooks/endpoints`
- `GET /v1/webhooks/endpoints/{endpoint_id}`
- `DELETE /v1/webhooks/endpoints/{endpoint_id}` (deactivate)
- Optional read-only event lookup stub:
  - `GET /v1/webhooks/events/{event_id}`
- Feature-flag gate for webhook v1 routes.
- Persistence model for endpoints/events.
- Integration tests.

## Non-Scope
- Background webhook delivery worker.
- Retry scheduler/backoff.
- HMAC send implementation.

## Steps
1. Add DB models for webhook endpoints/events.
2. Add v1 webhook route module with firm-scoped auth checks.
3. Register new router in API app.
4. Add integration tests for endpoint lifecycle and gating.
5. Run targeted tests and deploy.

## Acceptance Criteria
- Endpoint lifecycle works with persisted records.
- Invalid callback URL rejected.
- Disabled feature flag returns 404.
- Existing API v1 job tests remain passing.

