# Pass 058 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`
>
> Complete ALL sections before writing any implementation plan.
> No sections collapsed. No categories skipped.
> If these conditions are not met, implementation is forbidden.

---

## PASS TITLE

**Pass 058 - Chronology Integrity and Event Segmentation**

---

## 1. System State

**Stage**: Hardening -> early Productization

**Signal layer status**: Robustness stabilized through Pass 056 and compact-packet review policy recalibrated through Pass 057

**Leverage layer status**: Implemented but not the active bottleneck for this pass

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

This pass does not add speculative product scope. It strengthens the core product contract by preserving medically distinct phases in the chronology rather than collapsing them into summary nodes. That directly improves attorney trust and case usefulness without weakening existing robustness or quality gates.

**Active stage constraints:**

- No renderer-side chronology inference
- Preserve deterministic outputs and citation anchoring
- Do not weaken hard blockers or review gates to manufacture more events
- Keep extraction/projection changes case-type agnostic

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [x] Narrative inconsistency
- [ ] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [ ] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

**Which one is primary?**

Narrative inconsistency caused by timeline compression of clinically distinct phases into single summary events.

**Optional secondary (only if tightly related):**

Trust erosion risk

**Why is this the highest risk right now?**

Pass 056 and Pass 057 show the system now completes compact packets robustly, but the batch output shape still averages roughly one event per packet. That suggests the chronology is preserving packet survival, not treatment sequence. For PI use, sequence, escalation, and gap structure are product-critical.

---

## 3. Define the Failure Precisely

**What test fails today?**

No dedicated chronology-granularity test currently enforces separation of clinically distinct same-day phases such as ED presentation, imaging, discharge, procedure, or follow-up when they coexist in one packet.

**What artifact proves the issue?**

- `reference/pass_057/cloud_batch30_rerun_20260306/summary.json`
- Batch pattern: `events_total = 1` in 29 of 30 packets
- Current compression code paths:
  - `apps/worker/lib/grouping.py`
  - `apps/worker/steps/step09_dedup.py`
  - `apps/worker/project/chronology.py`

**Is this reproducible across packets?**

Yes. The compact MIMIC batch shows a systematic one-event pattern.

**Is this systemic or packet-specific?**

Systemic. Compression happens in shared grouping, deduplication, and projection merge logic.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- Distinct clinically meaningful phases in one packet are silently collapsed into one chronology row solely because they share date, page adjacency, or provider compatibility.

**Must be guaranteed:**

- Event segmentation preserves meaningful treatment phases when citation-backed evidence differentiates them.

**Must pass deterministically:**

- The same packet rerun twice yields the same event segmentation, chronology row count, and event ordering.
- A packet containing clearly separable ED + imaging + discharge or discharge + procedure content produces multiple chronology events deterministically.

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

Introduce an explicit event-segmentation policy boundary that distinguishes true duplicates from clinically distinct phases before dedup and projection merge steps. The architecture should make extraction own encounter segmentation, dedup own duplicate suppression, and projection own formatting/selection only.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-CI1

**Name**: CLINICALLY_DISTINCT_PHASES_NOT_COLLAPSED

**What must always be true after this pass?**

Citation-backed clinically distinct phases in one packet must remain separate chronology events unless a deterministic duplicate rule proves they are the same encounter.

**Where is it enforced?**

Expected enforcement target:
- event grouping / dedup / projection merge boundary
- likely `apps/worker/steps/step09_dedup.py` and `apps/worker/project/chronology.py`

**Where is it tested?**

Planned tests in new chronology-integrity coverage files.

**What is added to `governance/invariants.md`?**

A new `INV-CI1` entry documenting phase-preserving segmentation.

---

## 7. Tests Added

**Unit tests:**

- planned: same-day ED and discharge remain separate when evidence differs
- planned: discharge summary and operative/procedure note do not collapse into one event
- planned: duplicate same-day fragments still merge when they are true duplicates

**Integration tests (if any):**

- planned: chronology projection preserves multi-phase packet structure end-to-end

**Determinism comparison (if applicable):**

- same packet rerun twice yields same segmentation and ordering

**Artifact-level assertion (if applicable):**

- pass artifact should record before/after chronology row counts for a controlled segmentation fixture

**If no new test is added, justify why:**

Not applicable. This pass requires new tests.

**Total new tests:** TBD during implementation

---

## 8. Risk Reduced

This pass reduces which risks:

- [ ] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Manual review time
- [x] Maintenance cost

**Explain how each checked risk is reduced:**

- Trust risk: attorneys see real treatment sequence rather than compressed summary nodes.
- Variability: explicit segmentation policy removes accidental merge behavior.
- Manual review time: fewer chronologies need human reconstruction from compressed rows.
- Maintenance cost: merge/split rules become explicit architectural policy instead of side effects across layers.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes. It targets segmentation policy, not one injury type or one packet.

**Does it depend on a specific test packet?**

No.

**Could this break other case types?**

Yes, if over-splitting is introduced. The implementation must preserve duplicate suppression and avoid turning one encounter into many noisy fragments.

**Does it introduce silent failure risk?**

Yes, if segmentation becomes non-deterministic or keyword-driven. That is why this pass must enforce deterministic typed phase boundaries.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- Chronology compresses treatment sequence into vague single-event summaries
- Gaps, escalation, and follow-up structure are invisible even though records contain them

**Does this pass eliminate one of those risks?**

Yes. It directly targets chronology compression, which is a product-value ceiling for PI firms.

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
| 1 System State | Complete | Robustness solved; segmentation is next bottleneck |
| 2 Failure Class | Complete | Narrative inconsistency via chronology compression |
| 3 Failure Defined | Complete | One-event batch pattern across MIMIC reruns |
| 4 Binary Success | Complete | Distinct phases remain separate deterministically |
| 5 Arch Move | Complete | Explicit segmentation boundary |
| 6 Invariants | Complete | INV-CI1 planned |
| 7 Tests | Complete | New segmentation tests required |
| 8 Risk Reduced | Complete | Trust, variability, review time, maintenance |
| 9 Overfitting | Complete | General segmentation policy |
| 10 Cancellation | Complete | Directly tied to chronology usefulness |
| Prohibited Behaviors | Complete | No hidden weakening |
| Registry Update | Complete | Invariant file will be updated |
