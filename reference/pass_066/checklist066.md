# Pass 066 - Launch Acceptance Matrix

## 1. System State

**Stage**: Hardening -> early Productization

**Signal layer status**: Stabilized enough for validated-slice launch judgment through passes 56-65

**Leverage layer status**: Implemented but not the launch blocker in this pass

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

This pass adds a deterministic launch-contract artifact, not user-facing product behavior. It is safer than more blind hardening because it converts the existing validation evidence into an explicit go/no-go boundary and prevents launch claims from outrunning proof.

**Active stage constraints:**

- No weakening of safety gates to manufacture readiness
- No marketing/breadth claims unsupported by validated artifacts
- Renderer stays display-only
- Broad launch cannot be declared if OCR or case-type coverage is still under-proven

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

After passes 56-65, the remaining danger is not silent junk in the validated slice. It is launching too broadly, with undefined acceptance boundaries, and forcing firms to discover the unsupported packet classes themselves.

---

## 3. Define the Failure Precisely

**What test fails today?**

There is no reproducible artifact that says:
- what packet classes are validated
- what packet classes are only pilot-ready
- what packet classes are still blocked

That means launch scope is currently a judgment call instead of a deterministic contract.

**What artifact proves the issue?**

- `reference/pass_063/summary.json`
- `reference/pass_064/summary.json`
- `reference/pass_065/summary.json`
- `reference/pass_057/cloud_batch30_rerun_20260306/summary.json`
- `reference/pass_062/validation_summary.md`

These prove the evidence exists, but not yet as a single machine-generated readiness contract.

**Is this reproducible across packets?**

Yes. The lack of a launch matrix is systemic.

**Is this systemic or packet-specific?**

Systemic.

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- Broad launch must not be claimable from repo artifacts if OCR and coverage breadth remain blocked.

**Must be guaranteed:**

- A single generated `launch_acceptance_matrix.json` states whether CiteLine is:
  - ready for a narrow pilot
  - blocked for broad launch
- The matrix must cite the artifact evidence behind each decision.

**Must pass deterministically:**

- Re-running the acceptance generator against the same pass artifacts must produce the same readiness verdict.

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

- [x] Adding boundary enforcement?
- [x] Introducing a guard pattern?
- [x] Consolidating logic?
- [ ] Eliminating duplication?
- [x] Separating layers more cleanly?

**Describe the move:**

Introduce a reproducible launch-readiness boundary artifact that sits above individual pass summaries. The code path does not decide marketing scope; the matrix does. That separates product claims from ad hoc judgment and ties them directly to validated evidence.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-LA1

**Name**: LAUNCH_SCOPE_BOUND_BY_VALIDATED_MATRIX

**What must always be true after this pass?**

Launch scope claims must be derived from the generated acceptance matrix and cannot exceed the packet classes and failure modes actually validated in pass artifacts.

**Where is it enforced?**

`scripts/build_launch_acceptance_matrix.py` :: `build_matrix()`

**Where is it tested?**

`tests/unit/test_build_launch_acceptance_matrix.py`

**What is added to `governance/invariants.md`?**

A pass-66 registry entry for `INV-LA1`.

---

## 7. Tests Added

**Unit tests:**

- `tests/unit/test_build_launch_acceptance_matrix.py :: test_build_matrix_marks_narrow_pilot_ready_but_broad_launch_blocked` - asserts the matrix allows narrow pilot and blocks broad launch when OCR/corpus breadth remain unresolved

**Integration tests (if any):**

- none in this pass

**Determinism comparison (if applicable):**

- Generator output is deterministic for identical pass artifacts and asserted in the unit test

**Artifact-level assertion (if applicable):**

- `reference/pass_066/launch_acceptance_matrix.json` must record `narrow_pilot_ready=true` and `broad_launch_ready=false` for the current validated slice

**If no new test is added, justify why:**

Not applicable

**Total new tests:** 1

---

## 8. Risk Reduced

This pass reduces which risks:

- [x] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

- Legal risk: reduces overclaiming unsupported product scope to firms.
- Trust risk: lawyers and API clients get a precise statement of what has been proven.
- Variability: readiness is derived from artifacts, not memory.
- Maintenance cost: future passes have a single readiness contract to update.
- Manual review time: operators stop testing unsupported classes by accident.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes. It is a launch-governance layer, not packet logic.

**Does it depend on a specific test packet?**

No. It depends on pass summaries as a set.

**Could this break other case types?**

No. It does not change extraction or rendering behavior.

**Does it introduce silent failure risk?**

Low. Missing evidence becomes an explicit blocked dimension rather than a hidden assumption.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- Being told the system is broadly ready, then discovering that scans or unsupported case types fail in production
- Having no clear boundary between pilot-safe and unproven packet classes

**Does this pass eliminate one of those risks?**

Yes. It eliminates the second risk directly and sharply reduces the first by making unsupported scope explicit.

---

## Prohibited Behaviors Check

- [x] No silent fallback logic
- [x] No renderer inference
- [x] No non-deterministic ordering
- [x] No hidden policy defaults
- [x] No test-hiding instead of logic correction
- [x] No silent invariant erosion

---

## Invariant Registry Update

- [x] `governance/invariants.md` will be updated with `INV-LA1`
- [x] No existing invariant is weakened
