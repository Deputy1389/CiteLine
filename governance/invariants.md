# Citeline Invariant Registry

> Governed by: `reference/govpreplan.md`
> Rule: All architectural invariants must be registered here. No invariant may be violated
> without explicitly updating this registry. Silent invariant erosion is forbidden.

---

## Pass Folder Convention

All passes from 39 onward use: `reference/pass_0XX/` (zero-padded, e.g. `reference/pass_039/`).
Passes 36–38 predate this convention; do not rename them.

---

## Signal Layer Invariants (Pass 36)

### INV-S1 — PT_DERIVATION_INTEGRITY

derive_case_signals() pt_dated_encounter_count matches independent harness recomputation.

- **Enforced in**: `apps/worker/lib/settlement_features.py` :: `build_settlement_feature_pack()`
- **Tested in**: `scripts/verify_invariant_harness.py` :: `check_S1_pt_derivation_integrity()`
- **Introduced in**: Pass 36
- **Failure class protected**: Data integrity failure

### INV-A1 — PT_COUNT_CONSISTENCY

PT count claims in MEDIATION PDF must be consistent with signals.

- **Enforced in**: `apps/worker/steps/export_render/timeline_pdf.py` (renderer reads signal counts)
- **Tested in**: `scripts/verify_invariant_harness.py` :: `check_A1_pt_count_consistency()`
- **Introduced in**: Pass 36
- **Failure class protected**: Narrative inconsistency

### INV-A3 — NOISE_NOT_IN_OBJECTIVE_OR_IMAGING

No fax header noise lines in OBJECTIVE FINDINGS or IMAGING sections.

- **Enforced in**: `packages/shared/utils/noise_utils.py` :: `is_fax_header_noise()`
- **Tested in**: `scripts/verify_invariant_harness.py` :: `check_A3_noise_not_in_objective_or_imaging()`
- **Introduced in**: Pass 36
- **Failure class protected**: Signal distortion

### INV-B1 — TIER_FLOOR_RADICULOPATHY

If has_radiculopathy is true, the severity profile must not be labeled conservative-only.

- **Enforced in**: `apps/worker/lib/case_severity_index.py`
- **Tested in**: `scripts/verify_invariant_harness.py` :: `check_B1_tier_floor_radiculopathy()`
- **Introduced in**: Pass 36
- **Failure class protected**: Data integrity failure / Trust erosion risk

### INV-B2 — TIER_FLOOR_INJECTION_DATED

If has_injection_dated is true, the severity profile must contain Interventional or Surgical.

- **Enforced in**: `apps/worker/lib/case_severity_index.py`
- **Tested in**: `scripts/verify_invariant_harness.py` :: `check_B2_tier_floor_injection_dated()`
- **Introduced in**: Pass 36
- **Failure class protected**: Data integrity failure / Trust erosion risk

### INV-C1 — MINOR_CAP_CEILING

Minor cases (duration < 30 days, no injection/surgery/neuro) must not reach Interventional or Surgical tier.

- **Enforced in**: `apps/worker/lib/case_severity_index.py`
- **Tested in**: `scripts/verify_invariant_harness.py` :: `check_C1_minor_cap_ceiling()`
- **Introduced in**: Pass 36
- **Failure class protected**: Data integrity failure

### INV-S2 — HAS_SURGERY_DATED_IN_SIGNALS

settlement_features.py must emit has_surgery_dated (not only the aggregate has_surgery).

- **Enforced in**: `apps/worker/lib/settlement_features.py` :: `build_settlement_feature_pack()`
- **Tested in**: `tests/test_leverage_trajectory.py` :: `test_has_surgery_dated_backward_compat`
- **Introduced in**: Pass 38
- **Failure class protected**: Data integrity failure (silent surgery tier miss)

---

## Leverage Layer Invariants (Pass 37)

### INV-L1 — LEVERAGE_TIER_CONSISTENCY

If has_radiculopathy is true, the leverage band must be ELEVATED or higher.

- **Enforced in**: `apps/worker/steps/export_render/orchestrator.py`
- **Tested in**: `scripts/verify_invariant_harness.py` :: `check_L1_leverage_tier_consistency()`
- **Introduced in**: Pass 37
- **Failure class protected**: Trust erosion risk / Architectural coupling

---

## Policy Versioning Invariants (Pass 38)

### INV-P1 — POLICY_FINGERPRINT_MATCH

leverage_policy_registry.computed_fingerprint(version) must equal stored leverage_policy.fingerprint.

- **Enforced in**: `apps/worker/steps/export_render/orchestrator.py` (re-render check before compute_leverage_index)
- **Tested in**: `tests/test_leverage_policy_versioning.py` :: `test_policy_fingerprint_stable`, `test_fingerprint_mismatch_disables_leverage`
- **Introduced in**: Pass 38
- **Failure class protected**: Determinism variance

### INV-P2 — RERENDER_POLICY_PINNING

Stored run leverage_policy.version must equal the version used at compute time. Unknown version does not silently fallback.

- **Enforced in**: `apps/worker/steps/export_render/orchestrator.py` :: `get_policy()` (raises KeyError on unknown)
- **Tested in**: `tests/test_leverage_policy_versioning.py` :: `test_unknown_version_raises`, `test_rerender_uses_stored_policy_version`
- **Introduced in**: Pass 38
- **Failure class protected**: Determinism variance

---

## Trajectory Invariants (Pass 38)

### INV-T1 — TRAJECTORY_DATED_ONLY

All entries in escalation_events have date.is_known == True. Undated events are suppressed to INTERNAL debug only.

- **Enforced in**: `apps/worker/lib/settlement_features.py` :: escalation_events derivation loop
- **Tested in**: `tests/test_leverage_trajectory.py` :: `test_undated_event_not_in_escalation_events`
- **Introduced in**: Pass 38
- **Failure class protected**: Legal risk (undated escalation step = factual misrepresentation)

### INV-T2 — TRAJECTORY_INJECTION_PEAK

If has_injection_dated == True, trajectory.peak_level must be >= 4.

- **Enforced in**: `scripts/verify_invariant_harness.py` :: `check_T2_trajectory_injection_peak()`
- **Tested in**: `tests/test_leverage_trajectory.py` :: `test_injection_dated_yields_peak_level_4`
- **Introduced in**: Pass 38
- **Failure class protected**: Data integrity failure

### INV-T3 — TRAJECTORY_SURGERY_PEAK

If has_surgery_dated == True, trajectory.peak_level must be == 5.

- **Enforced in**: `scripts/verify_invariant_harness.py` :: `check_T3_trajectory_surgery_peak()`
- **Tested in**: `tests/test_leverage_trajectory.py` :: `test_surgery_dated_yields_peak_level_5`
- **Introduced in**: Pass 38
- **Failure class protected**: Data integrity failure

---

## Regression Enforcement Checks (Pass 39)

These are static and cross-run checks executed by `scripts/verify_invariant_harness.py`.
They are not runtime invariants but governance-enforcement checks required by govpreplan §6.

### CHECK-D1 — DETERMINISM_RERUN

derive_case_signals() called twice on the same evidence graph must return identical output.

- **Enforced in**: `scripts/verify_invariant_harness.py` :: `check_D1_determinism_rerun()`
- **Tested in**: harness D1 check (per fixture)
- **Introduced in**: Pass 39
- **Failure class protected**: Determinism variance

### CHECK-D2 — POLICY_PINNING

If ext["leverage_policy"]["version"] is present, its fingerprint must match the registry.

- **Enforced in**: `scripts/verify_invariant_harness.py` :: `check_D2_policy_pinning()`
- **Tested in**: harness D2 check (per fixture)
- **Introduced in**: Pass 39
- **Failure class protected**: Determinism variance

### CHECK-D3 — NO_MEDIATION_LEAKAGE

Policy fingerprint and param keys must not appear in mediation PDF bytes.

- **Enforced in**: `scripts/verify_invariant_harness.py` :: `check_D3_no_mediation_leakage()`
- **Tested in**: harness D3 check (per fixture)
- **Introduced in**: Pass 39
- **Failure class protected**: Export leakage

### CHECK-D4 — TRAJECTORY_SIGNALS_ONLY

leverage_trajectory.py must not import or access EvidenceGraph, evidence_graph, or eg_bytes.

- **Enforced in**: `scripts/verify_invariant_harness.py` :: `check_D4_trajectory_signals_only()` (static analysis)
- **Tested in**: harness D4 check (per run)
- **Introduced in**: Pass 39
- **Failure class protected**: Architectural coupling / layer bleed

### CHECK-D5 — RENDERER_DISPLAY_ONLY

timeline_pdf.py and mediation_sections.py must not call any compute functions.

- **Enforced in**: `scripts/verify_invariant_harness.py` :: `check_D5_renderer_display_only()` (static analysis)
- **Tested in**: harness D5 check (per run)
- **Introduced in**: Pass 39
- **Failure class protected**: Architectural coupling / layer bleed

---

## Escalation Traceability Invariants (Pass 40)

### INV-E1 — ESCALATION_TRACEABILITY

Every `trajectory.markers` entry on runs produced after Pass 40 must have a non-null
`source_anchor` — a deterministic sha256 hash of `(date|kind|sorted_source_page_numbers)[:16]`.

**Design note**: Raw EvidenceGraph `event_id` values are NOT used as the anchor because
they are generated with `uuid4()` at extraction time and are not stable across re-extraction.
`source_anchor` is computed from stable properties (date, kind, page numbers) instead.

**INTERNAL/MEDIATION split**: `source_anchor` and `policy_clause` are INTERNAL-only fields.
MEDIATION trajectory markers contain only `date`, `level`, `kind`. D3 enforces their absence
from MEDIATION PDF bytes.

- **Enforced in**: `apps/worker/lib/settlement_features.py` :: `_compute_source_anchor()` (computes at derivation); `apps/worker/lib/leverage_trajectory.py` (threads through markers); `apps/worker/steps/export_render/orchestrator.py` :: `_marker_to_internal()` / `_marker_to_mediation()` (INTERNAL/MEDIATION split)
- **Tested in**: `tests/test_leverage_trajectory.py` :: `test_markers_have_source_anchor`, `test_source_anchor_is_stable`; `scripts/verify_invariant_harness.py` :: `check_E1_escalation_traceability()`
- **Introduced in**: Pass 40
- **Failure class protected**: Trust erosion risk (govpreplan §5 compliance)
- **Legacy rule (Pass 41 tightened)**: Skip only when `run_metadata.pass` is absent or < 40.
  Previous skip condition (data-inferred: "if no marker has source_anchor") was bypassable by
  disabling `_compute_source_anchor()` entirely. Metadata-explicit skip closes that vector.

---

## Empirical Safety Invariants (Pass 41)

### INV-E2 — NO_ESCALATION_FROM_LOW_CONFIDENCE

Any trajectory event that increases trajectory level must have `confidence >= 0.80`.
Low-confidence events (`confidence < 0.80`) are filtered out before computing `peak_level`,
`monthly_levels`, and `markers` (Option B: structural, not marker-only).

**Confidence rules** (deterministic, rule-based):
- Explicit date + source pages populated → 0.90
- Explicit date + no source pages → 0.85
- No explicit date → 0.60 (excluded by INV-T1 upstream)

**Backward compatibility**: Pre-Pass-41 events without `confidence` key default to 0.90 (full trust).

- **Enforced in**: `apps/worker/lib/settlement_features.py` :: `_compute_escalation_confidence()` (computes confidence in escalation loop); `apps/worker/lib/leverage_trajectory.py` (filters events below threshold before computing peak/markers)
- **Tested in**: `tests/test_confidence_provenance.py` :: `test_injection_dated_confidence_is_high_when_dated`, `test_surgery_dated_confidence_is_high_when_dated`, `test_low_confidence_event_produces_low_anchor_score`; `tests/test_leverage_trajectory.py` :: `test_no_escalation_if_only_low_confidence_signal`; `scripts/verify_invariant_harness.py` :: `check_E2_no_escalation_from_low_confidence()`
- **Introduced in**: Pass 41
- **Failure class protected**: Trust erosion risk (signal distortion → severity inflation)

### CHECK-D6 — INTERNAL_VERSION_HEADER_PRESENT

Every INTERNAL PDF must contain the version header block (Signal Layer, Policy, Fingerprint,
Determinism). Rendered from pre-computed `ext["run_metadata"]` (established in Pass 040).

- **Enforced in**: `scripts/verify_invariant_harness.py` :: `check_D6_internal_version_header_present()`
- **Tested in**: harness D6 check (per-case, INTERNAL PDF only; skips if no INTERNAL PDF in fixture)
- **Introduced in**: Pass 41
- **Failure class protected**: Version transparency erosion

---

## Fixture Coverage

| Fixture | Band | Radiculopathy | Injection | Surgery | T2 | T3 | E1 |
|---|---|---|---|---|---|---|---|
| case1 | MODERATE | No | No | No | skip | skip | skip (pre-Pass-40) |
| case2 | ELEVATED | Yes | No | No | skip | skip | skip (pre-Pass-40) |
| case3_herniation | ELEVATED | Yes | No | No | skip | skip | skip (pre-Pass-40) |
| case4_soft_tissue | MODERATE | No | No | No | skip | skip | skip (pre-Pass-40) |
| case5_injection_dated | HIGH | Yes | **Yes** | No | **ENFORCED** | skip | **ENFORCED** |
| case6_surgery_dated | TRIAL_LEVEL | Yes | No | **Yes** | skip | **ENFORCED** | **ENFORCED** |

**Pass 41 closure**: case5 and case6 are synthetic fixtures added to close the documented
T2/T3 coverage gap. INV-T2 runs as enforced on case5; INV-T3 runs as enforced on case6.
E1 runs as enforced on both (run_metadata.pass=41 triggers explicit Pass-40 guard).

**case7 (ambiguous fixture)**: Not included in Pass 41 scope. Current confidence floor for
dated events is 0.85 (explicit date, no source pages) — above the 0.80 INV-E2 threshold.
INV-E2 never activates on current live data. case7 is deferred to Pass 042.
---

## Observability Invariants (Pass 042)

### INV-OBS1 -- RUN_METADATA_PERSISTED

**Status:** ENFORCED  
**Introduced:** Pass 042  
**Failure class protected:** Production blindness

**Definition:** Every completed production run (any terminal status) must persist `signal_layer_version`, `policy_fingerprint`, `packet_page_count`, and `error_class` before the run status record is closed.

**Enforcement:** `apps/worker/lib/observability.write_run_observability()` called from `pipeline_persistence.persist_pipeline_state()` (success) and `pipeline._fail_run()` (failure). All observability writes are wrapped in `try/except` - a DB hiccup must never surface as a run failure.

**Tests:** `tests/unit/test_run_observability.py` - 7 tests pass.

**Supporting tables:** `invariant_results`, `run_metrics` (append-only audit logs, Pass 042).

**Operator queries:** `reference/operator_queries.sql`  
**Alerting triggers:** `reference/alerting_v1.md`

---

## Queue + Idempotency Invariants (Pass 043)

### INV-Q1 � ARTIFACT_COMMIT_GATE

A run cannot be marked `succeeded` unless all artifact types listed in `REQUIRED_ARTIFACT_TYPES`
(defined in `apps/worker/lib/queue.py`) are present and have `write_state = 'committed'`.
Absent artifact types are treated the same as uncommitted ones.

- **Enforced in**: `apps/worker/lib/queue.py` :: `mark_succeeded()` � raises `RuntimeError` if any required type is missing or not committed.
- **Tested in**: `tests/unit/test_queue_idempotency.py` :: `test_mark_succeeded_requires_all_required_artifacts_committed`, `test_atomic_artifact_write_committed_only`
- **Introduced in**: Pass 043
- **Failure class protected**: Trust erosion (succeeded run with missing artifacts)

### INV-Q2 � IDEMPOTENCY_KEY_DEDUP

Submitting the same `(firm_id, packet_sha256, export_mode, policy_version, signal_layer_version)`
to the queue never creates a second run if the original is queued, running, or succeeded.

**Idempotency scope is policy-bound**: If `policy_version` or `signal_layer_version` changes, the key
changes and a new run is intentionally created. Do not remove these fields from the key.

- **Enforced in**: `apps/worker/lib/queue.py` :: `enqueue_run()`
- **Tested in**: `tests/unit/test_queue_idempotency.py` :: `test_idempotency_key_same_input_returns_same_run`, `test_idempotency_key_failed_allows_retry_same_run_id_attempt_increments`
- **Introduced in**: Pass 043
- **Failure class protected**: Trust erosion (duplicate runs from double-submission)

### INV-Q3 � REQUIRED_ARTIFACT_REGISTRY_CENTRALIZED

The set of artifact types required for run completion is defined in exactly one place:
`REQUIRED_ARTIFACT_TYPES` (frozenset at the top of `apps/worker/lib/queue.py`).
`mark_succeeded()` queries the DB against this registry and never hardcodes artifact names.

- **Enforced in**: `apps/worker/lib/queue.py` :: `REQUIRED_ARTIFACT_TYPES` + `mark_succeeded()`
- **Tested in**: `tests/unit/test_queue_idempotency.py` :: `test_mark_succeeded_requires_all_required_artifacts_committed`
- **Introduced in**: Pass 043
- **Failure class protected**: Silent succeeded-with-missing-artifact as pipeline adds new artifact types

---

## Pass 044 — INV-P1: Drift Baseline Never Silent Skip

**Invariant:** When a previous-pass baseline exists for a case, the drift checker must return
status RUN (comparison was performed), not SKIP. A drift SKIP must always include
a human-readable reason string and be counted in drift_counters.skip.

**Baseline resolution order (precedence):**
1. <prev_out>/output/<case_id>/run_metadata.json (per-case subdir layout, from Pass 044)
2. <prev_out>/<case_id>_run_metadata.json (legacy flat layout, Pass 039–043)

**Enforced in:** scripts/run_regression.py (un_drift_check, _load_prev_metadata)

**Tested in:** 	ests/integration/test_parallel_uploads.py
  - 	est_drift_baseline_run_not_skip
  - 	est_flat_baseline_fallback
  - 	est_missing_baseline_returns_skip_reason

---

## Pass 044 — INV-P2: Simulator Exits Non-Zero on Any Bad State

**Invariant:** scripts/simulate_parallel_uploads.py must exit with code 1 and record the
offending event whenever any of the following bad states are detected:

| Code | Description |
|------|-------------|
| DOUBLE_CLAIM | Same un_id claimed by two workers with overlapping lease windows |
| SUCCESS_WITHOUT_ARTIFACTS | status=succeeded while any REQUIRED_ARTIFACT_TYPES missing/uncommitted |
| DUPLICATE_COMMITTED_ARTIFACT | Same (run_id, artifact_type) committed twice with different hashes |
| IDEMPOTENCY_VIOLATION | Same idempotency_key returns different un_id while prior is queued/running/succeeded |
| GHOST_RUNNING | status=running with lock_expires_at expired beyond 2x heartbeat interval |
| DETERMINISM_FAILURE | Re-run of same packet yields different artifact hashes |

**Enforced in:** scripts/simulate_parallel_uploads.py (detect_bad_states_once, _record_bad_state)

**Tested in:** 	ests/integration/test_parallel_uploads.py::test_simulator_produces_zero_bad_states

---

## Pass 044 — INV-P3: Heartbeat Jitter Prevents Thundering Herd

**Invariant:** Each HeartbeatThread must apply a random initial jitter of up to 20% of
HEARTBEAT_INTERVAL before beginning its first update. This prevents all workers that
restart simultaneously (e.g., after a crash-recovery) from hammering the database at the
same instant.

**Enforced in:** pps/worker/runner.py (HeartbeatThread.run)

**No dedicated test** — operational hardening, verified by simulator under concurrent load.

## Pass 045 Invariants

**INV-Q4**: Key finding for a timeline row must be selected from a fact whose text has the highest token overlap with the event's primary citation page snippets -- not blindly from candidate position [0]. Enforced by _pick_key_finding_page_anchored() in 	imeline_pdf.py.

**INV-Q5**: Promoted findings with lignment_status not in {None, '', 'PASS'} must have headline_eligible=False and must not appear in settlement driver snapshot bullets. Enforced in nnotate_renderer_manifest_claim_context_alignment in step_renderer_manifest.py.

**INV-Q6**: Regression suite must include a cross-contamination fixture (primary injury + unrelated clinical system) with explicit expectations that unrelated content does not drive injury-tier signals. See 	ests/fixtures/invariants/case7_cross_contamination/.

## Compact Packet Policy Invariants (Pass 57)

### INV-CP1 - COMPACT_PACKET_NOT_VOLUME_GATED

Compact citation-backed packets must not be downgraded solely by prose-density or generic
required-bucket soft gates.

- **Enforced in**: `apps/worker/lib/compact_packet_policy.py`; consumed by `apps/worker/lib/attorney_readiness.py`, `apps/worker/lib/luqa.py`, and `apps/worker/lib/quality_gates.py`
- **Tested in**: `tests/unit/test_attorney_readiness.py` :: `test_attorney_density_soft_gate_is_relaxed_for_five_page_compact_packets`; `tests/unit/test_luqa.py` :: `test_luqa_relaxes_density_and_verbatim_soft_gates_for_five_page_compact_packets`; `tests/unit/test_quality_gates_wrapper.py` :: `test_five_page_compact_packet_visit_bucket_quality_does_not_trigger_review`
- **Introduced in**: Pass 57
- **Failure class protected**: Review burden inflation

---

## Chronology Integrity Invariants (Pass 58)

### INV-CI1 - CLINICALLY_DISTINCT_PHASES_NOT_COLLAPSED

Citation-backed clinically distinct phases in one packet must remain separate chronology events unless a deterministic duplicate rule proves they are the same encounter.

- **Enforced in**: `apps/worker/steps/events/clinical.py` :: `_extract_block_events()` and `apps/worker/steps/events/clinical_assembler.py` :: `append_to_event()`
- **Tested in**: `tests/unit/test_event_extraction.py` :: `test_same_block_splits_ed_and_discharge_into_distinct_events`, `test_same_block_splits_admission_and_procedure_into_distinct_events`; `tests/unit/test_dedup.py` :: `test_same_page_phase_distinct_events_do_not_merge`
- **Introduced in**: Pass 58
- **Failure class protected**: Narrative inconsistency / Trust erosion risk

---

### INV-CP2 - SEGMENTED_COMPACT_PACKET_NOT_REPENALIZED

Compact packets that preserve a small number of clinically distinct phases must not lose compact-policy protection solely because segmentation improved.

- **Enforced in**: `apps/worker/lib/compact_packet_policy.py`
- **Tested in**: `tests/unit/test_attorney_readiness.py` :: `test_attorney_density_soft_gate_is_relaxed_for_four_phase_compact_packets`; `tests/unit/test_luqa.py` :: `test_luqa_relaxes_density_and_verbatim_soft_gates_for_four_phase_compact_packets`; `tests/unit/test_quality_gates_wrapper.py` :: `test_four_phase_compact_packet_visit_bucket_quality_does_not_trigger_review`
- **Introduced in**: Pass 59
- **Failure class protected**: Review burden inflation

---

## Promotion Hygiene Invariants (Pass 60)

### INV-PF1 - PROMOTED_FINDING_SUBSTANCE_FLOOR

`renderer_manifest.promoted_findings` may include only citation-backed substantive findings. Synthetic generic diagnosis labels, administrative record identifiers, and timing-only treatment boilerplate must not be promoted.

- **Enforced in**: `apps/worker/steps/step_renderer_manifest.py` :: `_promoted_findings_from_claim_rows()`
- **Tested in**: `tests/unit/test_renderer_manifest.py` :: `test_renderer_manifest_suppresses_generic_synthetic_and_admin_claim_rows`, `test_renderer_manifest_preserves_substantive_treatment_rows_when_clinically_meaningful`
- **Introduced in**: Pass 60
- **Failure class protected**: Trust erosion risk

---
