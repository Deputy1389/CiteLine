# Pass 050 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`

---

## PASS TITLE

**Pass 050 - Webhook Event Delivery + Replay (`/v1/webhooks/events/{event_id}/replay`)**

---

## 1. System State

**Stage**: Hardening -> early productization

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

Webhook delivery and replay are required contract capabilities for API integrations and can be added at control-plane boundaries without changing extraction determinism.

---

## 2. Failure Class Targeted

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [x] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

**Primary**: Trust erosion risk

**Why highest now?**

Partners can register endpoints (Pass 049) but receive no callbacks, so integration reliability is unproven.

---

## 3. Define the Failure Precisely

**What fails today?**

`/v1/jobs` state changes do not create or dispatch webhook events; replay path does not exist.

**Artifact proving issue**

`apps/api/routes/jobs_v1.py` has no webhook emission calls; `apps/api/routes/webhooks_v1.py` has no replay POST endpoint.

**Reproducibility**

Systemic.

---

## 4. Binary Success State

After this pass:

- Must be impossible: a `/v1/jobs` create/cancel operation completes without recording webhook events for active firm endpoints.
- Must be guaranteed: replay endpoint can re-dispatch a stored webhook event and persist attempt outcome.
- Must pass deterministically: integration tests assert event creation, signed delivery call, and replay response updates.

---

## 5. Architectural Move

- [x] Adding boundary enforcement
- [x] Introducing a guard pattern
- [x] Consolidating logic
- [ ] Eliminating duplication
- [x] Separating layers more cleanly

**Move**

Centralize webhook event recording+dispatch helpers in `webhooks_v1` and invoke from `jobs_v1` lifecycle boundaries.

---

## 6. Invariant Introduced

**Invariant ID**: INV-API-05

**Name**: WEBHOOK_EVENT_DISPATCH_CONTRACT

**Invariant**

For enabled v1 routes, each emitted job lifecycle event is persisted with attempt metadata and can be replayed deterministically by event id.

**Enforced in**

`apps/api/routes/webhooks_v1.py`

**Tested in**

`tests/integration/test_api_v1_webhooks.py`

---

## 7. Tests Added

- Integration:
  - job create emits webhook event record for active endpoint
  - replay endpoint dispatches and updates delivery state
  - replay endpoint requires enabled feature flag

---

## 8. Risk Reduced

- [ ] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Maintenance cost
- [x] Manual review time

---

## 9. Overfitting Check

Generalizable and packet-agnostic; no medical content assumptions.

---

## 10. Cancellation Test

Cancellation trigger avoided:
- "Webhook integrations are documented but callbacks never arrive or cannot be replayed."

This pass directly addresses that reliability gap.
