# Pass 053 - Checklist

> Governance contract: `reference/govpreplan.md`
> Invariant registry: `governance/invariants.md`
>
> Completed before implementation.

---

## PASS TITLE

**Pass 053 - Competitive Uplift: Deterministic Clinical Abstraction + Litigation Superiority**

---

## 1. System State

**Stage**: Hardening -> early Productization (pilot-readiness + competitive uplift)

**Signal layer status**: In progress

**Leverage layer status**: Implemented (defense/cause/leverage features exist; refinement needed)

**Are we allowed to add features this pass?** Yes

**If yes, why is this safer than further hardening?**

Core reliability gates and cloud stability work are in place. The largest remaining adoption blocker is attorney-facing abstraction completeness and strategy framing versus competitors. This pass adds typed, deterministic structures that reduce trust risk and prevent renderer-side drift.

**Active stage constraints:**

- No renderer inference of medical semantics
- No uncited statements on Pages 1-5
- Preserve `needs_review` degradation for invariant breaks
- MEDIATION LLM policy unchanged

---

## 2. Failure Class Targeted

This pass must eliminate or reduce exactly ONE primary failure class:

- [ ] Data integrity failure
- [ ] Narrative inconsistency
- [x] Required bucket miss
- [ ] Determinism variance
- [ ] Export leakage
- [ ] Signal distortion
- [ ] Trust erosion risk
- [ ] Review burden inflation
- [ ] Performance bottleneck
- [ ] Architectural coupling / layer bleed

**Which one is primary?**

Required bucket miss

**Optional secondary (only if tightly related):**

Trust erosion risk

**Why is this the highest risk right now?**

Competitive review from `reference/Diagnosis.md` indicates attorneys perceive summary-thin visits as weaker than EvenUp-style abstraction. Missing required visit buckets directly lowers confidence even when citations exist.

---

## 3. Define the Failure Precisely

**What test fails today?**

No deterministic contract enforces encounter-level bucket completeness with encounter-type-aware rules; quality gates can pass outputs that are strategically weak but not structurally complete.

**What artifact proves the issue?**

- `reference/Diagnosis.md` gap analysis
- Current rendering fallbacks in `apps/worker/steps/export_render/timeline_pdf.py`

**Is this reproducible across packets?**

Yes

**Is this systemic or packet-specific?**

Systemic

---

## 4. Define the Binary Success State

After this pass, the following must be true:

**Must be impossible:**

- Exportable encounter rows without encounter-type-conditioned required bucket evaluation.
- Injury clusters/severity/causation timeline built from ad hoc sources outside canonical diagnosis registry lineage.

**Must be guaranteed:**

- `visit_abstraction_registry` exists with deterministic bucket population.
- `provider_role_registry` exists and drives escalation logic.
- `causation_timeline_registry` exists and is citation-backed.
- `injury_cluster_severity` exists with severity inputs surfaced.

**Must pass deterministically:**

- Same input + config -> same registry rows, ordering, and hash.

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

Adopt canonical dataflow:
`visit_abstraction_registry -> diagnosis_registry (canonical) -> injury_clusters -> injury_cluster_severity -> causation_timeline_registry -> treatment_escalation_path`.

All downstream strategic features must derive from canonical registries, not parallel extraction logic.

---

## 6. Invariant Introduced or Strengthened

**Invariant ID**: INV-53

**Name**: ENCOUNTER_TYPE_CONDITIONED_BUCKET_COMPLETENESS

**What must always be true after this pass?**

Each exportable encounter must satisfy required buckets for its encounter type (or emit explicit missing-bucket reason), and threshold violations must degrade run status to `needs_review`.

**Where is it enforced?**

Planned pipeline + quality gate enforcement (`apps/worker/pipeline.py`, `apps/worker/lib/quality_gates.py`, new registry step files).

**Where is it tested?**

Planned unit/integration tests for PT/ER/specialist encounter profiles and deterministic output hashes.

**What is added to `governance/invariants.md`?**

INV-53 with encounter-type matrix and degradation policy.

---

## 7. Tests Added

**Unit tests:**

- `tests/unit/test_visit_abstraction_registry.py :: test_bucket_requirements_by_encounter_type`
- `tests/unit/test_diagnosis_registry.py :: test_diagnosis_registry_is_canonical_source`
- `tests/unit/test_provider_role_registry.py :: test_provider_role_classification_deterministic`
- `tests/unit/test_injury_cluster_severity.py :: test_cluster_severity_inputs_and_score`
- `tests/unit/test_causation_timeline_registry.py :: test_causation_chain_has_required_rungs`
- `tests/unit/test_quality_gates_wrapper.py :: test_bucket_threshold_violation_forces_needs_review`

**Integration tests (if any):**

- `tests/integration/test_pipeline_visit_abstraction_contract.py`
- `tests/integration/test_pipeline_competitive_registry_contract.py`

**Determinism comparison (if applicable):**

- Same packet twice -> identical registry hash bundle.

**Artifact-level assertion (if applicable):**

- `reference/pass_053/competitive_gap_validation.json` with bucket coverage, role coverage, causation rung coverage, and severity coverage.

**If no new test is added, justify why:**

N/A

**Total new tests:** 8 (planned minimum)

---

## 8. Risk Reduced

This pass reduces which risks:

- [x] Legal risk
- [x] Trust risk
- [x] Variability
- [x] Maintenance cost
- [x] Manual review time

**Explain how each checked risk is reduced:**

- Legal: stronger deterministic causation and citation coverage.
- Trust: no thin visit abstractions hidden by narrative polish.
- Variability: encounter-type matrix removes subjective bucket expectations.
- Maintenance: canonical registry lineage prevents parallel feature logic.
- Review time: explicit missing-bucket reasons localize remediation.

---

## 9. Overfitting Check

**Is this solution generalizable?**

Yes

**Does it depend on a specific test packet?**

No

**Could this break other case types?**

Only if encounter-type rules are overfit to spine packets; non-spine coverage is required in tests.

**Does it introduce silent failure risk?**

No, if review degradation and machine-readable reasons are enforced.

---

## 10. Cancellation Test

**If a $1k/month PI firm used this system:**

What would make them cancel?

- Incomplete visit abstraction despite available records
- Weak causation framing and defense-prep utility

**Does this pass eliminate one of those risks?**

Yes. It directly addresses both via deterministic registries and strategic artifacts.

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
| 1 System State | Complete | Competitive uplift justified |
| 2 Failure Class | Complete | Primary = required bucket miss |
| 3 Failure Defined | Complete | systemic gap documented |
| 4 Binary Success | Complete | registry and causation/severity guarantees |
| 5 Arch Move | Complete | canonical lineage enforced |
| 6 Invariants | Complete | INV-53 upgraded with encounter-type matrix |
| 7 Tests | Complete | 8 planned tests |
| 8 Risk Reduced | Complete | includes maintenance via deduped lineage |
| 9 Overfitting | Complete | non-spine coverage required |
| 10 Cancellation | Complete | addresses abstraction + strategy deficits |
| Prohibited Behaviors | Complete | guarded by architecture rules |
| Registry Update | Complete | explicit |

Checklist is complete and internally consistent.
Implementation plan is in `reference/pass_053/plan.md`.
