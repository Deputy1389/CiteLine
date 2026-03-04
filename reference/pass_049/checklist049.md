# Pass 049 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`

---

## PASS TITLE

**Pass 049 - Phase 1 Webhook Endpoint Registry (`/v1/webhooks/endpoints`)**

---

## 1. System State

**Stage**: Hardening -> early productization

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

Webhook endpoint registry is a control-plane boundary needed for API-first integrations and does not alter extraction logic.

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

Without webhook registration API, partners must poll indefinitely and cannot rely on callback contracts.

---

## 3. Define the Failure Precisely

**What fails today?**

No `/v1/webhooks/endpoints` route exists to register callback URLs.

**Artifact proving issue**

Current API route surface under `apps/api/routes` contains no webhook registry route.

**Reproducibility**

Systemic.

---

## 4. Binary Success State

After this pass:

- Must be impossible: creating webhooks without a valid callback URL.
- Must be guaranteed: create/list/get/deactivate endpoint operations are available under `/v1/webhooks/endpoints`.
- Must pass deterministically: integration tests verify endpoint lifecycle behavior and feature-flag gating.

---

## 5. Architectural Move

- [x] Adding boundary enforcement
- [x] Introducing a guard pattern
- [x] Consolidating logic
- [ ] Eliminating duplication
- [x] Separating layers more cleanly

**Move**

Add explicit control-plane persistence and API boundary for webhook endpoint management.

---

## 6. Invariant Introduced

**Invariant ID**: INV-API-04

**Name**: WEBHOOK_ENDPOINT_REGISTRY_CONTRACT

**Invariant**

Registered webhook endpoints must be firm-scoped, URL-validated, and lifecycle-managed via v1 routes.

**Enforced in**

`apps/api/routes/webhooks_v1.py`

**Tested in**

`tests/integration/test_api_v1_webhooks.py`

---

## 7. Tests Added

- Integration:
  - create/list/get/deactivate endpoint lifecycle
  - invalid URL rejected
  - feature flag disabled returns `404`

---

## 8. Risk Reduced

- [ ] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Maintenance cost
- [x] Manual review time

---

## 9. Overfitting Check

Generalizable and packet-agnostic; no case-type logic.

---

## 10. Cancellation Test

Cancellation trigger avoided:
- "Integration says webhook support exists but no registration contract."

This pass directly removes that risk.

