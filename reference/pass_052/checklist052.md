# Pass 052 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`
>
> Completed before implementation.

---

## PASS TITLE

**Pass 052 - Pilot Stabilization (Strict/Pilot Quality Mode + Reliability Ops)**

---

## 1. System State

**Stage**: Hardening -> early Productization (pilot-readiness)

**Signal layer status**: In progress (multi-pass hardening active)

**Leverage layer status**: Implemented but still calibration-bound

**Are we allowed to add features this pass?** No

**If yes, why is this safer than further hardening?**

N/A. This pass is stabilization-only and avoids net-new product scope.

**Active stage constraints:**

- No new extraction features
- No renderer keyword logic
- No weakening citation invariants
- Preserve needs_review degradation for revenue-critical failures

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

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

**Which one is primary?**

Trust erosion risk

**Optional secondary (only if tightly related):**

Review burden inflation

**Why is this the highest risk right now?**

Pilot users need deterministic output flow. Hard-blocking on LUQA meta-language failures can prevent export delivery even when citation-backed output exists, causing perceived instability and churn during pilot onboarding.

---

## 3. Define the Failure Precisely

**What test fails today?**

In strict-only behavior, `LUQA_META_LANGUAGE_BAN` is always treated as hard and sets `export_status=BLOCKED`, preventing pilot exports.

**What artifact proves the issue?**

`apps/worker/lib/quality_gates.py` hard-failure policy and classification path.

**Is this reproducible across packets?**

Yes; whenever LUQA meta-language findings appear.

**Is this systemic or packet-specific?**

Systemic.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- Pilot mode cannot hard-block solely because of `LUQA_META_LANGUAGE_BAN`.

**Must be guaranteed:**

- In pilot mode, LUQA meta-language violations are soft failures and produce `REVIEW_RECOMMENDED` (not `BLOCKED`).
- In strict mode, prior hard-block behavior remains unchanged.

**Must pass deterministically:**

- Given identical failures containing `LUQA_META_LANGUAGE_BAN`, `quality_mode="pilot"` yields soft/review and `quality_mode="strict"` yields hard/blocked.

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

Is this pass:

- [x] Adding boundary enforcement?
- [x] Introducing a guard pattern?
- [ ] Consolidating logic?
- [ ] Eliminating duplication?
- [x] Separating layers more cleanly?

**Describe the move:**

Introduce explicit `quality_mode` as a typed run-level policy input (`strict|pilot`) and route it through production and eval entrypoints into quality gate classification logic, instead of implicit global hardcoded behavior.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-52

**Name**: QUALITY_MODE_POLICY_EXPLICIT

**What must always be true after this pass?**

Quality gate hard/soft classification must be determined by explicit `quality_mode` and be deterministic for strict vs pilot execution.

**Where is it enforced?**

`apps/worker/lib/quality_gates.py` classification helpers and `run_quality_gates`.

**Where is it tested?**

`tests/unit/test_quality_gates_wrapper.py` pilot-vs-strict assertions.

**What is added to `governance/invariants.md`?**

No registry update in this pass (existing governance registry file is not present in current tree); invariant is recorded in pass artifact docs and test suite for enforcement.

---

## 7. Tests Added

**Unit tests:**

- `tests/unit/test_quality_gates_wrapper.py :: test_quality_mode_pilot_demotes_luqa_meta_language_ban`
- `tests/unit/test_quality_gates_wrapper.py :: test_quality_mode_strict_keeps_luqa_meta_language_ban_hard`

**Integration tests (if any):**

- None in this pass.

**Determinism comparison (if applicable):**

- Same synthetic input, mode switch only; classification output must flip deterministically.

**Artifact-level assertion (if applicable):**

- Pass 52 cloud run summary must include success of core artifact retrieval (`evidence_graph.json`, `chronology.pdf`, `missing_records.csv`).

**If no new test is added, justify why:**

N/A.

**Total new tests:** 2

---

## 8. Risk Reduced

This pass reduces which risks:

- [ ] Legal risk
- [x] Trust risk
- [x] Variability
- [ ] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

Pilot mode prevents unnecessary hard blocks while preserving review signaling, producing more predictable run completion and fewer manual escalations for non-critical LUQA meta-language issues.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes; it is mode-based policy, not packet-specific logic.

**Does it depend on a specific test packet?**

No.

**Could this break other case types?**

No direct case-type coupling; policy applies uniformly across all packets.

**Does it introduce silent failure risk?**

No; failures are still recorded and surfaced, only severity tier changes in pilot mode.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- Frequent blocked exports despite usable cited outputs
- Inconsistent run outcomes across similar packets

**Does this pass eliminate one of those risks?**

Yes. It reduces blocked-export frequency in pilot mode while preserving explicit `needs_review` signaling.

---

## Prohibited Behaviors Check (govpreplan §10)

Confirm none of the following are introduced by this pass:

- [x] Silent fallback logic
- [x] Renderer inference (renderer computes anything)
- [x] Non-deterministic ordering
- [x] Hidden policy defaults
- [x] Direct EvidenceGraph access from Trajectory
- [x] Fixing tests by hiding outputs instead of correcting logic
- [x] Policy changes without version increment

Note: checkmarks indicate "confirmed not introduced".

---

## Invariant Registry Update

- [x] `governance/invariants.md` will be updated with all new invariants introduced by this pass
- [x] No existing invariant is silently removed or weakened

Note: registry file does not exist in this workspace snapshot; invariant is captured in pass documentation + tests.

---

## Checklist Summary

| Section | Status | Note |
|---|---|---|
| 1 System State | Complete | Stabilization-only scope |
| 2 Failure Class | Complete | Primary = trust erosion |
| 3 Failure Defined | Complete | strict-only hard block identified |
| 4 Binary Success | Complete | strict/pilot deterministic flip |
| 5 Arch Move | Complete | explicit quality_mode threading |
| 6 Invariants | Complete | INV-52 defined |
| 7 Tests | Complete | 2 unit tests planned |
| 8 Risk Reduced | Complete | trust/variability/review burden |
| 9 Overfitting | Complete | packet-agnostic |
| 10 Cancellation | Complete | blocked export risk addressed |
| Prohibited Behaviors | Complete | no prohibited behavior added |
| Registry Update | Complete | documented caveat |

Checklist is complete and internally consistent.
Implementation plan is in `reference/pass_052/plan.md`.
