# Pass XXX — Checklist Template

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`
>
> Complete ALL sections before writing any implementation plan.
> No sections collapsed. No categories skipped.
> If these conditions are not met, implementation is forbidden.

---

## PASS TITLE

**Pass XXX — [Title]**

---

## 1. System State

**Stage**: [Current stage, e.g. Hardening → early Productization]

**Signal layer status**: [Locked at Pass XX / In progress]

**Leverage layer status**: [Implemented at Pass XX / Not yet]

**Are we allowed to add features this pass?** Yes / No

**If yes, why is this safer than further hardening?**

[Explain why the feature addition reduces trust risk, improves determinism, reduces review burden, or formalizes an invariant. If none of these apply, it is not allowed.]

**Active stage constraints:**

- [List any constraints inherited from the current stage]
- [e.g. No valuation logic. No percentile benchmarking.]

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
- [ ] Architectural coupling / layer bleed

**Which one is primary?**

[Name the primary failure class]

**Optional secondary (only if tightly related):**

[Name secondary, or omit]

**Why is this the highest risk right now?**

[Explain with evidence from the current codebase state]

---

## 3. Define the Failure Precisely

**What test fails today?**

[Describe the specific test or assertion that demonstrates the failure]

**What artifact proves the issue?**

[File name and line number, or artifact path]

**Is this reproducible across packets?**

[Yes / No — explain]

**Is this systemic or packet-specific?**

[Systemic / Packet-specific — explain]

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- [State exactly what must become structurally impossible]

**Must be guaranteed:**

- [State exactly what must be structurally guaranteed]

**Must pass deterministically:**

- [Write binary test criteria, e.g. "Re-rendering a stored run cannot change leverage band or score."]

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

Is this pass:

- [ ] Adding boundary enforcement?
- [ ] Introducing a guard pattern?
- [ ] Consolidating logic?
- [ ] Eliminating duplication?
- [ ] Separating layers more cleanly?

**Describe the move:**

[Explain the structural change. If this is just a conditional patch, rethink it.]

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-XX

**Name**: [INVARIANT_NAME]

**What must always be true after this pass?**

[One-sentence invariant definition]

**Where is it enforced?**

[File + function]

**Where is it tested?**

[Test file + test function]

**What is added to `governance/invariants.md`?**

[Confirm the registry entry that will be added]

---

## 7. Tests Added

**Unit tests:**

- [test_file.py :: test_function_name — what it asserts]

**Integration tests (if any):**

- [test_file.py :: test_function_name — what it asserts]

**Determinism comparison (if applicable):**

- [Describe any re-render or cross-run comparison test]

**Artifact-level assertion (if applicable):**

- [e.g. reference/pass_XXX/invariant_report.json must contain specific entries]

**If no new test is added, justify why:**

[Justification — this is rarely acceptable]

**Total new tests:** XX

---

## 8. Risk Reduced

This pass reduces which risks:

- [ ] Legal risk
- [ ] Trust risk
- [ ] Variability
- [ ] Maintenance cost
- [ ] Manual review time

**Explain how each checked risk is reduced:**

[Explanation]

---

## 9. Overfitting Check

**Is this solution generalizable?**

[Yes / No — explain]

**Does it depend on a specific test packet?**

[Yes (which one) / No]

**Could this break other case types?**

[Yes (how) / No — explain]

**Does it introduce silent failure risk?**

[Yes (how) / No — explain]

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- [List 1–2 cancellation-class failures]

**Does this pass eliminate one of those risks?**

[Yes — explain which one and how. If No, reconsider the pass.]

---

## Prohibited Behaviors Check (govpreplan §10)

Confirm none of the following are introduced by this pass:

- [ ] Silent fallback logic
- [ ] Renderer inference (renderer computes anything)
- [ ] Non-deterministic ordering
- [ ] Hidden policy defaults
- [ ] Direct EvidenceGraph access from Trajectory
- [ ] Fixing tests by hiding outputs instead of correcting logic
- [ ] Policy changes without version increment

---

## Invariant Registry Update

- [ ] `governance/invariants.md` will be updated with all new invariants introduced by this pass
- [ ] No existing invariant is silently removed or weakened

---

## Checklist Summary

| Section | Status | Note |
|---|---|---|
| 1 System State | | |
| 2 Failure Class | | |
| 3 Failure Defined | | |
| 4 Binary Success | | |
| 5 Arch Move | | |
| 6 Invariants | | |
| 7 Tests | | |
| 8 Risk Reduced | | |
| 9 Overfitting | | |
| 10 Cancellation | | |
| Prohibited Behaviors | | |
| Registry Update | | |

Checklist is complete and internally consistent.
Implementation plan is in plan.md.
