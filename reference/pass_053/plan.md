# Pass 053 Plan - Competitive Uplift Execution (Revised)

## Objective
Move from parity to superiority by combining EvenUp-level medical abstraction clarity with Linecite-native litigation intelligence.

Primary pass target remains: **Required bucket miss**.

## Diagnosis Cross-Check: Already Implemented vs Missing

### Already Implemented (Keep / Reuse)
- Provider normalization: `apps/worker/lib/provider_normalize.py`
- Encounter dedup: `apps/worker/steps/step09_dedup.py`
- Gap and missing-record detection: `step11_gaps.py`, `step15_missing_records.py`
- Billing/specials: `step16_billing_lines.py`, `step17_specials_summary.py`
- Litigation intelligence primitives: claim rows, causation ladders/chains, defense attack maps, settlement leverage model
- Citation traceability substrate: evidence graph + citations + renderer manifest

### Missing / Weak (Pass 053 scope)
1. Deterministic visit abstraction completeness by encounter type
2. Canonical diagnosis registry lineage driving downstream features
3. Provider role classification for escalation logic
4. Explicit causation timeline artifact
5. Injury cluster severity model tied to clinical evidence intensity

## Critical Structural Upgrades Added

### Upgrade 1: Injury Severity Model (Superiority Feature)
Add `injury_cluster_severity` derived from canonical registries:
- `cluster_id`
- `severity_score_0_100`
- `surgery_present`
- `injection_present`
- `imaging_support_level`
- `treatment_intensity_index`
- `escalation_level`
- `mri_pathology_present`
- `treatment_duration_days`
- `pt_visit_count`
- `specialist_involvement`

Purpose: attorneys reason in injury severity posture, not diagnosis lists.
Severity output is a direct upstream input to settlement leverage interpretation.

### Upgrade 2: Provider Role Detection (Deterministic Escalation)
Add `provider_role_registry` with normalized roles:
- `ER`
- `primary_care`
- `specialist`
- `imaging`
- `therapy`
- `surgery`

Purpose: make escalation and causation paths deterministic and explainable.

### Upgrade 3: Causation Timeline Registry (Superiority Feature)
Add `causation_timeline_registry` with required rungs:
- incident
- first_treatment
- first_diagnosis
- imaging_confirmation
- specialist_confirmation
- surgical_repair_or_high_intensity_equivalent

Include citations and missing-rung reasons.

## Architectural Risk Controls

### Risk 1: Registry Explosion / Duplicate Logic
Control:
- Canonical lineage contract:
  `visit_abstraction_registry -> diagnosis_registry (canonical) -> injury_clusters -> injury_cluster_severity`
- No downstream feature may parse raw events independently if canonical source exists.

### Risk 2: False Positives in Bucket Completeness
Control:
- Encounter-type-conditioned required bucket matrix.

Example matrix (v1):
- `PT`: complaints, treatments, objective_findings(optional), diagnoses(optional)
- `ER`: complaints, objective_findings, diagnostics_or_assessment, diagnoses_or_impression, treatments
- `Specialist`: complaints, objective_findings_or_exam, diagnoses, treatment_plan

If required buckets for that encounter type are missing -> explicit reason + quality gate policy.

## Refined Execution Order (Dependency-Safe)

### Step 1 - Visit Abstraction Registry
Implement deterministic per-encounter bucket extraction + encounter type tagging.

### Step 2 - Diagnosis Registry (Canonical Source)
Implement diagnosis/ICD/first-seen/provider/citation table.

### Step 3 - Injury Cluster Engine
Derive clusters from diagnosis registry only.

### Step 4 - Provider Role Classification
Map normalized providers to role taxonomy for strategy features.

### Step 5 - Treatment Escalation + Causation Timeline
Build ordered escalation path and explicit causation rungs using role-aware encounters.

### Step 6 - Quality Gates + Status Policy
Add encounter-type bucket completeness gating and degrade to `needs_review` on threshold violation.

## Data Contract Additions (Planned)

`evidence_graph.extensions` and manifest additions:
- `visit_abstraction_registry`
- `diagnosis_registry`
- `injury_clusters`
- `injury_cluster_severity`
- `provider_role_registry`
- `treatment_escalation_path`
- `causation_timeline_registry`

Renderer remains formatting-only consumer.

## Test Plan (Mandatory)

### Unit
- `test_visit_abstraction_registry.py`
- `test_diagnosis_registry.py`
- `test_provider_role_registry.py`
- `test_injury_cluster_severity.py`
- `test_causation_timeline_registry.py`
- `test_quality_gates_wrapper.py` (encounter-type-conditioned completeness)

### Integration
- pipeline emits registry contracts with stable schemas
- API artifact routes remain compatible
- status degradation for completeness threshold works (`needs_review`)

### Golden/Cloud
- existing spine packets
- at least one non-spine packet (shoulder/knee/TBI)
- assert no placeholders, consistent counts, citation completeness, and rung coverage

## Competitive Validation Artifacts
- `reference/pass_053/competitive_gap_matrix.md`
- `reference/pass_053/encounter_bucket_matrix.md`
- `reference/pass_053/competitive_gap_validation.json`
- `reference/pass_053/registry_contract_snapshot.json`

## Long-Term Moat Note (Out of Scope for Pass 053)
To counter competitor outcome-data moat, define follow-on track:
- `case_resolution_capture` (settlement/verdict/jurisdiction/defense firm/policy limits)
- feature-outcome warehouse
- leverage benchmarking models

This is **not** pass 053 implementation scope, but must be staged as pass 054+ roadmap.

## Definition of Done
- Encounter-type-conditioned abstraction completeness enforced
- Canonical diagnosis lineage implemented and reused downstream
- Provider roles + causation timeline + injury severity artifacts emitted
- Quality gates degrade to `needs_review` when thresholds fail
- Tests pass across spine and non-spine coverage
- Competitive gap matrix confirms parity + superiority deltas
