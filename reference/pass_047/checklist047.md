# Pass 047 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`
>
> Complete ALL sections before writing any implementation plan.
> No sections collapsed. No categories skipped.
> If these conditions are not met, implementation is forbidden.

---

## PASS TITLE

**Pass 047 - Phase 1 API Facade (`/v1/jobs`)**

---

## 1. System State

**Stage**: Hardening -> early productization

**Signal layer status**: Existing run pipeline and quality gates active

**Leverage layer status**: API-first facade not yet implemented

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

Adding a versioned facade for job lifecycle reduces coupling risk and establishes a single contract used by first-party and partner integrations without changing extraction semantics.

**Active stage constraints:**

- Keep revenue-critical output invariants unchanged
- Preserve current run statuses including `needs_review`
- No renderer-side inference or keyword logic

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [ ] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [x] Architectural coupling / layer bleed

**Which one is primary?**

Architectural coupling / layer bleed

**Optional secondary (only if tightly related):**

Trust erosion risk

**Why is this the highest risk right now?**

Without a canonical API contract, internal and external consumers diverge and status/artifact behavior drifts, causing integration failures and blank review flows.

---

## 3. Define the Failure Precisely

**What test fails today?**

No `/v1/jobs` lifecycle endpoint exists as a stable facade; clients must rely on internal routes and models.

**What artifact proves the issue?**

Current route surface in `apps/api/routes` lacks versioned `jobs` facade endpoints.

**Is this reproducible across packets?**

Yes.

**Is this systemic or packet-specific?**

Systemic.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- New consumers should not need direct calls to legacy unversioned run route shapes for basic job lifecycle.

**Must be guaranteed:**

- Feature-flagged `/v1/jobs` supports create/status/list-artifacts/cancel and maps to existing run behavior.

**Must pass deterministically:**

- API tests prove `/v1/jobs` endpoints return consistent status mapping and artifact payloads for seeded run records.

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

Is this pass:

- [x] Adding boundary enforcement?
- [x] Introducing a guard pattern?
- [x] Consolidating logic?
- [ ] Eliminating duplication?
- [x] Separating layers more cleanly?

**Describe the move:**

Introduce a versioned API facade layer (`/v1/jobs`) guarded by a feature flag, reusing existing run orchestration and persistence while presenting a stable async contract.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-API-02

**Name**: JOB_LIFECYCLE_CONTRACT_STABILITY

**What must always be true after this pass?**

`/v1/jobs` lifecycle endpoints must preserve canonical status semantics and artifact discoverability without bypassing quality gates.

**Where is it enforced?**

`apps/api/routes` facade route handlers and shared mapping helpers.

**Where is it tested?**

New API route tests under `apps/api/tests` for create/get/artifacts/cancel lifecycle.

**What is added to `governance/invariants.md`?**

Deferred to governance pass with full invariant registry update after implementation verification.

---

## 7. Tests Added

**Unit tests:**

- API route tests for `/v1/jobs` create/status/artifacts/cancel.

**Integration tests (if any):**

- None in this pass.

**Determinism comparison (if applicable):**

- Not applicable.

**Artifact-level assertion (if applicable):**

- Not applicable.

**If no new test is added, justify why:**

N/A - tests are required and added.

**Total new tests:** 4 (planned)

---

## 8. Risk Reduced

This pass reduces which risks:

- [ ] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

A single API contract reduces behavior drift across clients, lowers bespoke integration maintenance, and reduces manual troubleshooting of status/artifact mismatches.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes.

**Does it depend on a specific test packet?**

No.

**Could this break other case types?**

No direct case-type dependency.

**Does it introduce silent failure risk?**

No; route feature flag defaults to existing behavior when disabled.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- Dashboard shows inconsistent run status vs partner integration
- Artifacts unavailable from one channel but present in another

**Does this pass eliminate one of those risks?**

Yes - it aligns channels on a shared job lifecycle contract.

---

## Prohibited Behaviors Check (govpreplan section 10)

Confirm none of the following are introduced by this pass:

- [x] Silent fallback logic
- [x] Renderer inference (renderer computes anything)
- [x] Non-deterministic ordering
- [x] Hidden policy defaults
- [x] Direct EvidenceGraph access from Trajectory
- [x] Fixing tests by hiding outputs instead of correcting logic
- [x] Policy changes without version increment

---

## Invariant Registry Update

- [ ] `governance/invariants.md` will be updated with all new invariants introduced by this pass
- [x] No existing invariant is silently removed or weakened

---

## Checklist Summary

| Section | Status | Note |
|---|---|---|
| 1 System State | Complete | Productization pass with constraints retained |
| 2 Failure Class | Complete | Architectural coupling targeted |
| 3 Failure Defined | Complete | Missing versioned facade identified |
| 4 Binary Success | Complete | Lifecycle contract success criteria defined |
| 5 Arch Move | Complete | Facade + feature flag boundary introduced |
| 6 Invariants | Complete | Invariant defined for this pass |
| 7 Tests | Complete | Route tests planned |
| 8 Risk Reduced | Complete | Drift/maintenance risks reduced |
| 9 Overfitting | Complete | Generalizable design confirmed |
| 10 Cancellation | Complete | Cancellation risks addressed |
| Prohibited Behaviors | Complete | No prohibited behavior introduced |
| Registry Update | Complete | No silent weakenings |
