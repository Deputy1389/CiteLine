# Pass 056 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`
>
> Completed before implementation.

---

## PASS TITLE

**Pass 056 - Global Robustness & Edge-Case Sweep**

---

## 1. System State

**Stage**: Hardening -> robustness expansion

**Signal layer status**: In progress

**Leverage layer status**: Implemented, but still consuming signal-layer assumptions

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

This pass converts hidden fragility into explicit policy. The changes are not product-surface features; they are boundary and degradation controls that prevent unusual but valid medical records from being discarded or crashing the export path.

**Active stage constraints:**

- No renderer-side medical inference
- No uncited statements on Pages 1-5
- MEDIATION LLM policy remains unchanged
- Unusual input must degrade to `needs_review` or `partial`, not crash the pipeline

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [ ] Required bucket miss
- [x] Determinism variance
- [ ] Export leakage
- [x] Signal distortion
- [ ] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

**Which one is primary?**

Signal distortion

**Optional secondary (only if tightly related):**

Determinism variance

**Why is this the highest risk right now?**

Recent MIMIC-IV synthetic regressions showed that valid records were being treated as invalid because of hardcoded date bands, alpha-numeric quality ratios, and renderer crash invariants. That means the pipeline can silently suppress or completely fail on valid-but-unusual source material.

---

## 3. Define the Failure Precisely

**What test fails today?**

The current codebase has no single unified robustness test; instead, the failure is observable in code paths that reject valid future-dated, historic, or highly structured records. MIMIC-IV synthetic packets trigger these assumptions.

**What artifact proves the issue?**

- `packages/shared/utils/clinical_utils.py:41`
- `apps/worker/steps/step06_dates.py:204`
- `apps/worker/steps/step02_text_acquire.py:150`
- `apps/worker/quality/text_quality.py:123`
- `apps/worker/steps/step03_classify.py:133`
- `apps/worker/steps/export_render/timeline_pdf.py:3157`

**Is this reproducible across packets?**

Yes

**Is this systemic or packet-specific?**

Systemic

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- Valid pages are dropped solely because their dates fall outside a hardcoded modern-year band.
- Structured tables or flowsheets are classified as garbage solely because punctuation exceeds alpha-numeric ratios.
- Short-form clinical rows are treated as non-medical merely because they are compact or symbol-heavy.
- Renderer invariants terminate the run when they can instead emit machine-readable blockers and degrade status.

**Must be guaranteed:**

- Date plausibility is governed by a shared policy with sentinel suppression separated from historical/future validity.
- Page classification uses weighted evidence, tie-breaking, and dominance rules rather than simple early-return keyword counts.
- Text quality scoring recognizes compact medical shorthand as valid signal.
- Render-time invariant failures are surfaced in artifacts and run status instead of uncaught runtime crashes where feasible.

**Must pass deterministically:**

- The same unusual packet always produces the same classification, warnings, blocker codes, and terminal run status.

---

## 5. Architectural Move (Not Patch)

This pass makes the following architectural move(s):

Is this pass:

- [x] Adding boundary enforcement?
- [x] Introducing a guard pattern?
- [x] Consolidating logic?
- [x] Eliminating duplication?
- [x] Separating layers more cleanly?

**Describe the move:**

Replace scattered sanity heuristics with a shared robustness policy:

`date plausibility policy -> text quality policy -> page classification scoring -> export degradation policy`

The renderer should report blocked conditions; the pipeline should own the decision to degrade status. Duplicate date sanity implementations and ad hoc thresholds should be collapsed into shared utilities.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-56

**Name**: VALID_UNUSUAL_INPUT_MUST_DEGRADE_NOT_CRASH

**What must always be true after this pass?**

Valid but unusual medical input formats, date eras, and structured text layouts must produce deterministic warnings/blockers and a terminal status, not a pipeline crash caused by hardcoded sanity assumptions.

**Where is it enforced?**

Planned in shared date/text policy utilities, classifier scoring, and export orchestration status handling.

**Where is it tested?**

Planned unit tests for future/historic dates and structured text, plus integration tests proving renderer blockers degrade status instead of raising uncaught exceptions.

**What is added to `governance/invariants.md`?**

INV-56 documenting unusual-input tolerance, shared date plausibility policy, and degrade-not-crash behavior.

---

## 7. Tests Added

**Unit tests:**

- `tests/unit/test_date_plausibility_policy.py :: test_future_synthetic_dates_are_not_sentinel`
- `tests/unit/test_date_plausibility_policy.py :: test_historic_dates_are_allowed_when_not_placeholder`
- `tests/unit/test_text_quality.py :: test_structured_table_text_not_flagged_as_garbage`
- `tests/unit/test_text_quality.py :: test_medical_short_form_rows_count_as_signal`
- `tests/unit/test_step03_classify.py :: test_summary_page_not_drowned_by_lab_density`
- `tests/unit/test_step03_classify.py :: test_first_section_header_breaks_keyword_density_tie`
- `tests/unit/test_renderer_blockers.py :: test_ed_render_gap_sets_blocker_without_runtime_crash`

**Integration tests (if any):**

- `tests/integration/test_pipeline_unusual_date_packet.py :: test_future_year_packet_completes`
- `tests/integration/test_pipeline_structured_text_packet.py :: test_structured_lab_summary_packet_completes_with_warnings`
- `tests/integration/test_export_degrades_on_render_blocker.py :: test_render_blocker_returns_needs_review_not_exception`

**Determinism comparison (if applicable):**

- Re-run the same synthetic packet twice and assert identical blocker codes, page classifications, and artifact hashes for robustness-related extensions.

**Artifact-level assertion (if applicable):**

- `reference/pass_056/robustness_matrix.json` must enumerate all triggered warnings/blockers and show no uncaught crash condition.

**If no new test is added, justify why:**

N/A

**Total new tests:** 9

---

## 8. Risk Reduced

This pass reduces which risks:

- [x] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

- Legal: valid records are no longer dropped because they do not resemble the expected packet shape.
- Trust: attorneys and operators get explicit blockers instead of silent omissions or crashes.
- Variability: shared plausibility rules replace duplicated year cutoffs and threshold drift.
- Maintenance: robustness policy is centralized instead of scattered across parser, classifier, and renderer code.
- Manual review time: warnings become actionable because the system finishes and records why it degraded.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes

**Does it depend on a specific test packet?**

No

**Could this break other case types?**

Yes, if implemented with new injury-specific keyword overrides. The pass must stay format-aware, not case-type-specific.

**Does it introduce silent failure risk?**

No, if every downgrade path writes explicit blocker codes and avoids hidden fallback behavior.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- The pipeline crashes on a valid packet because the data is old, synthetic, or unusually structured.
- The export silently drops major sections because a summary page was mislabeled as labs or garbage.

**Does this pass eliminate one of those risks?**

Yes. It directly targets both by replacing brittle assumptions with shared tolerance policy and degrade-not-crash handling.

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
| 1 System State | Complete | robustness expansion pass |
| 2 Failure Class | Complete | primary = signal distortion |
| 3 Failure Defined | Complete | systemic fragility documented |
| 4 Binary Success | Complete | degrade-not-crash success state |
| 5 Arch Move | Complete | shared robustness policy |
| 6 Invariants | Complete | INV-56 defined |
| 7 Tests | Complete | focused robustness suite planned |
| 8 Risk Reduced | Complete | trust/legal/variability reduction |
| 9 Overfitting | Complete | packet-agnostic guardrails |
| 10 Cancellation | Complete | addresses crash/silent-drop risk |
| Prohibited Behaviors | Complete | preserved |
| Registry Update | Complete | explicit |

Checklist is complete and internally consistent.
Implementation plan is in `reference/pass_056/plan.md`.
