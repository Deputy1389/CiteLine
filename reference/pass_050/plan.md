# Pass 050 - Plan

## Objective
Implement v1 webhook event delivery and replay so job lifecycle callbacks are persisted, dispatched with signature headers, and operator-replayable.

## Scope
- Emit webhook events from `/v1/jobs` lifecycle transitions currently handled in API.
  - `job.pending` on create
  - `job.cancelled` on cancel
- Add signed webhook delivery helper (`X-Citeline-Signature`, HMAC-SHA256).
- Add bounded retry attempts during dispatch and persist attempt metadata.
- Add replay route:
  - `POST /v1/webhooks/events/{event_id}/replay`
- Add integration tests with mocked outbound HTTP.

## Non-Scope
- Background async delivery daemon / scheduler.
- Multi-day retry orchestration and DLQ.
- Worker-originated status emission (`job.running`, terminal success/failed from worker transitions).

## Steps
1. Add dispatch helpers in `webhooks_v1.py` for event payload, signature, and retry delivery.
2. Expose replay endpoint for existing `webhook_events` records.
3. Wire jobs route create/cancel to emit lifecycle events through shared helpers.
4. Add integration tests for emission and replay behavior.
5. Run targeted tests and ship scoped commit.

## Acceptance Criteria
- Job create inserts at least one webhook event for each active endpoint of the firm.
- Replay endpoint attempts delivery and updates `delivery_status`, `attempt_count`, and `last_attempt_at`.
- Signature header is present on outbound webhook request.
- Existing v1 jobs + webhook tests remain passing.
