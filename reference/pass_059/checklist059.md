# Pass 059 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`
>
> Complete ALL sections before writing any implementation plan.
> No sections collapsed. No categories skipped.
> If these conditions are not met, implementation is forbidden.

---

## PASS TITLE

**Pass 059 - Segmentation-Aware Compact Packet Gates**

---

## 1. System State

**Stage**: Hardening -> early Productization

**Signal layer status**: Robustness stabilized through Pass 056, compact review policy calibrated through Pass 057, chronology segmentation improved in Pass 058

**Leverage layer status**: Not the active bottleneck for this pass

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

This pass does not add visible feature scope. It repairs policy drift introduced by the correct segmentation improvement in Pass 058, so review gates judge compact packets by evidence sufficiency rather than by the number of preserved phases.

**Active stage constraints:**

- Preserve deterministic outputs
- Do not weaken hard blockers
- No renderer inference
- Keep policy generic and packet-shape based

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

Review burden inflation caused by compact-packet gates that are not segmentation-aware.

**Optional secondary (only if tightly related):**

Narrative inconsistency

**Why is this the highest risk right now?**

Pass 058 increased `Patient_10002930.pdf` from `2` to `4` events, which is the correct chronology improvement. But the same packet immediately regressed from `success` to `needs_review` because the compact-packet policy still caps at `3` substantive events/projection rows.

---

## 3. Define the Failure Precisely

**What test fails today?**

A compact 5-page packet with `4` preserved chronology phases fails compact-packet suppression and re-triggers soft review gates even though no hard blocker exists.

**What artifact proves the issue?**

- `reference/pass_058/cloud_rerun_patient_10002930/pipeline_parity_report.json`
- `reference/pass_058/cloud_rerun_patient_10002930/summary.json`

**Is this reproducible across packets?**

Yes. Any compact packet that becomes more faithfully segmented can cross the current `<=3` compact threshold and get re-downgraded.

**Is this systemic or packet-specific?**

Systemic. The shared helper in `apps/worker/lib/compact_packet_policy.py` is too strict for segmentation-preserving packets.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- A compact packet is downgraded solely because correct segmentation increased its phase count from 3 to 4.

**Must be guaranteed:**

- Compact-packet policy remains active after chronology segmentation preserves clinically distinct phases.

**Must pass deterministically:**

- The same segmented compact packet reruns as `success` with stable failure-code absence.

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

Is this pass:

- [ ] Adding boundary enforcement?
- [x] Introducing a guard pattern?
- [x] Consolidating logic?
- [ ] Eliminating duplication?
- [x] Separating layers more cleanly?

**Describe the move:**

Strengthen the shared compact-packet policy so it is based on compact packet shape after segmentation, not on pre-segmentation summary count assumptions.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-CP2

**Name**: SEGMENTED_COMPACT_PACKET_NOT_REPENALIZED

**What must always be true after this pass?**

Compact packets that preserve a small number of clinically distinct phases must not lose compact-policy protection solely because segmentation improved.

**Where is it enforced?**

`apps/worker/lib/compact_packet_policy.py`

**Where is it tested?**

`tests/unit/test_attorney_readiness.py`, `tests/unit/test_luqa.py`, `tests/unit/test_quality_gates_wrapper.py`

**What is added to `governance/invariants.md`?**

A new `INV-CP2` entry documenting segmentation-aware compact policy.

---

## 7. Tests Added

**Unit tests:**

- compact 5-page 4-phase packet still suppresses AR density soft gate
- compact 5-page 4-phase packet still suppresses LUQA density/verbatim soft gates
- compact 5-page 4-encounter packet still suppresses wrapper visit-bucket soft gate

**Integration tests (if any):**

- cloud rerun of `Patient_10002930.pdf` is acceptance proof

**Determinism comparison (if applicable):**

- rerun of the same packet should remain `success`

**Artifact-level assertion (if applicable):**

- pass-59 cloud rerun summary must show `success` for `Patient_10002930.pdf`

**If no new test is added, justify why:**

Not applicable.

**Total new tests:** 3

---

## 8. Risk Reduced

This pass reduces which risks:

- [x] Trust risk
- [x] Variability
- [x] Manual review time

**Explain how each checked risk is reduced:**

- Trust risk: the system no longer punishes improved chronology fidelity.
- Variability: segmentation and gate policy stop fighting each other.
- Manual review time: compact faithful chronologies do not bounce back into review.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes. It targets compact segmented packet shape, not one packet ID.

**Does it depend on a specific test packet?**

No.

**Could this break other case types?**

Low risk if compact policy remains restricted to small page-count and small phase-count packets.

**Does it introduce silent failure risk?**

No. Only soft review suppression is affected; hard blockers stay intact.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- Better chronology fidelity causes more review downgrades instead of fewer
- Similar compact packets oscillate between `success` and `needs_review`

**Does this pass eliminate one of those risks?**

Yes. It aligns compact-packet review policy with the improved segmentation model.

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
| 1 System State | Complete | Segmentation improved; gates lag behind |
| 2 Failure Class | Complete | Review burden inflation |
| 3 Failure Defined | Complete | 4-phase compact packet re-downgraded |
| 4 Binary Success | Complete | Segmented compact packet remains success |
| 5 Arch Move | Complete | Shared segmentation-aware compact policy |
| 6 Invariants | Complete | INV-CP2 |
| 7 Tests | Complete | 3 unit tests + cloud rerun |
| 8 Risk Reduced | Complete | Trust, variability, review time |
| 9 Overfitting | Complete | Shape-based policy |
| 10 Cancellation | Complete | Prevents segmentation-vs-gate conflict |
| Prohibited Behaviors | Complete | No hidden weakening |
| Registry Update | Complete | Invariant registry updated |
