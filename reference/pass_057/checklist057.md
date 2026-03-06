# Pass 057 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`
>
> Complete ALL sections before writing any implementation plan.
> No sections collapsed. No categories skipped.
> If these conditions are not met, implementation is forbidden.

---

## PASS TITLE

**Pass 057 - Compact Packet Quality-Gate Recalibration**

---

## 1. System State

**Stage**: Hardening -> early Productization

**Signal layer status**: In progress through Pass 056 robustness hardening

**Leverage layer status**: Implemented but not in scope for this pass

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

This pass does not add user-visible product scope. It formalizes a policy boundary so compact citation-backed packets are judged by evidence sufficiency instead of prose density. That reduces false review burden and strengthens determinism in terminal status decisions.

**Active stage constraints:**

- No renderer inference or keyword-scanning fallback
- No policy weakening that hides real blockers
- Preserve degrade-not-crash behavior from Pass 056
- Keep outputs deterministic across reruns

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
- [x] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

**Which one is primary?**

Review burden inflation from compact-packet false positives in production quality gates.

**Optional secondary (only if tightly related):**

Required bucket miss

**Why is this the highest risk right now?**

Pass 056 removed the crash-class failures for MIMIC packets. The remaining batch outlier `Patient_10002930` completed but was downgraded only by soft review gates: `AR_FACT_DENSITY_LOW`, `LUQA_FACT_DENSITY`, and `VISIT_BUCKET_REQUIRED_MISSING`. That is unnecessary review load on valid compact packets and is now the main blocker to pilot trust.

---

## 3. Define the Failure Precisely

**What test fails today?**

A compact 5-page, 2-event packet with citation-backed chronology still lands in `needs_review` because compact-packet suppression only applies up to 4 pages.

**What artifact proves the issue?**

- `reference/pass_056/cloud_batch30_20260305/artifacts/03_Patient_10002930/pipeline_parity_report.json`
- `reference/pass_056/cloud_batch30_20260305/artifacts/03_Patient_10002930/run_final.json`

**Is this reproducible across packets?**

Yes. The same soft-gate pattern appeared in earlier Pass 056 MIMIC triage and remains reproducible on the one outlier in the 30-packet batch.

**Is this systemic or packet-specific?**

Systemic. The current compact-packet rule is duplicated across AR, LUQA, and quality-gates wrapper and relies on a strict page-count cutoff that misclassifies short but valid packets.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- A citation-backed compact packet is downgraded solely because it has low prose density or incomplete generic visit buckets.

**Must be guaranteed:**

- Compact-packet status decisions are made by one shared policy, not three duplicated local heuristics.

**Must pass deterministically:**

- Re-running the same compact packet with the same artifacts yields the same terminal status and the same soft failure codes.
- The `Patient_10002930` outlier flips from `needs_review` to `success` if no real blocker exists.

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

Is this pass:

- [ ] Adding boundary enforcement?
- [x] Introducing a guard pattern?
- [x] Consolidating logic?
- [x] Eliminating duplication?
- [x] Separating layers more cleanly?

**Describe the move:**

Move compact-packet classification into one shared policy helper and make AR, LUQA, and wrapper-level visit-bucket review all consume the same policy result. This replaces duplicated page-count heuristics with a single evidence-sufficiency-aware gate boundary.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-CP1

**Name**: COMPACT_PACKET_NOT_VOLUME_GATED

**What must always be true after this pass?**

Compact citation-backed packets may not be downgraded solely by prose-density or generic required-bucket soft gates.

**Where is it enforced?**

`apps/worker/lib/compact_packet_policy.py` and consumers in `attorney_readiness.py`, `luqa.py`, and `quality_gates.py`

**Where is it tested?**

`tests/unit/test_attorney_readiness.py`, `tests/unit/test_luqa.py`, `tests/unit/test_quality_gates_wrapper.py`

**What is added to `governance/invariants.md`?**

A new `INV-CP1` entry documenting the shared compact-packet sufficiency rule.

---

## 7. Tests Added

**Unit tests:**

- `tests/unit/test_attorney_readiness.py :: test_attorney_density_soft_gate_is_relaxed_for_five_page_compact_packets` - asserts AR density soft gate is suppressed for the 5-page outlier shape
- `tests/unit/test_luqa.py :: test_luqa_relaxes_density_and_verbatim_soft_gates_for_five_page_compact_packets` - asserts LUQA density/verbatim soft gates are suppressed for the same class
- `tests/unit/test_quality_gates_wrapper.py :: test_five_page_compact_packet_visit_bucket_quality_does_not_trigger_review` - asserts wrapper-level visit-bucket review is suppressed for compact 5-page packets

**Integration tests (if any):**

- None planned initially; cloud rerun of `Patient_10002930.pdf` is the acceptance proof.

**Determinism comparison (if applicable):**

- Same packet rerun on cloud should produce stable `success` status and no new soft-failure codes.

**Artifact-level assertion (if applicable):**

- `reference/pass_056/cloud_batch30_20260305/artifacts/03_Patient_10002930/run_final.json` equivalent rerun artifact must flip from `needs_review` to `success`.

**If no new test is added, justify why:**

Not applicable.

**Total new tests:** 3

---

## 8. Risk Reduced

This pass reduces which risks:

- [ ] Legal risk
- [x] Trust risk
- [x] Variability
- [ ] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

- Trust risk: valid compact packets stop appearing arbitrarily downgraded.
- Variability: one shared compact policy removes drift between AR, LUQA, and wrapper status logic.
- Manual review time: compact admission/discharge packets no longer create unnecessary review queues.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes. It is based on compact packet shape and evidence sufficiency, not on a single packet ID.

**Does it depend on a specific test packet?**

No.

**Could this break other case types?**

Low risk if compact classification remains strict and only suppresses soft gates. Dense or contradictory packets still go through the existing hard and soft gate paths.

**Does it introduce silent failure risk?**

No. It removes only review-only false positives and leaves hard blockers intact.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- Valid short packets repeatedly downgraded for review with no real defect
- Inconsistent terminal status across similar compact packets

**Does this pass eliminate one of those risks?**

Yes. It targets the false-review downgrade pattern directly and replaces it with evidence-based compact-packet policy.

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

---

## Invariant Registry Update

- [x] `governance/invariants.md` will be updated with all new invariants introduced by this pass
- [x] No existing invariant is silently removed or weakened

---

## Checklist Summary

| Section | Status | Note |
|---|---|---|
| 1 System State | Complete | Compact-packet recalibration only |
| 2 Failure Class | Complete | Review burden inflation |
| 3 Failure Defined | Complete | 5-page compact outlier still downgraded |
| 4 Binary Success | Complete | Outlier flips without weakening hard blockers |
| 5 Arch Move | Complete | Shared compact-packet policy helper |
| 6 Invariants | Complete | INV-CP1 added |
| 7 Tests | Complete | 3 unit tests planned |
| 8 Risk Reduced | Complete | Trust, variability, review time |
| 9 Overfitting | Complete | General shape-based rule |
| 10 Cancellation | Complete | False review downgrade reduced |
| Prohibited Behaviors | Complete | No hidden weakening |
| Registry Update | Complete | Invariant file will be updated |
