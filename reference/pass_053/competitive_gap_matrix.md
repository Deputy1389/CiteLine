# Pass 053 Competitive Gap Matrix

## Purpose
Track what is already implemented, what is partially implemented, and what Pass 053 must close to move from parity to superiority.

Scoring:
- `Implemented`: present and production-wired
- `Partial`: present but incomplete/non-deterministic/weakly surfaced
- `Missing`: not implemented as typed contract

---

## A. Medical Abstraction Parity

| Capability | Competitive Importance | Current Status | Evidence Path | Pass 53 Action | Acceptance Criteria |
|---|---|---|---|---|---|
| Visit-level structured abstraction (complaints/objective/diagnostics/diagnosis/treatment/referrals/limitations/causation) | Critical | Partial | `apps/worker/steps/export_render/timeline_pdf.py` fallback patterns; diagnosis thinness in diagnosis notes | Build `visit_abstraction_registry` with encounter-type bucket rules | 100% exportable encounters include required buckets for encounter type or explicit missing reason |
| Diagnosis registry with ICD, first seen, provider, citation | Critical | Partial | diagnosis mentions exist, but no canonical registry contract | Implement `diagnosis_registry` as canonical source | Registry rows deterministic and citation-backed; exposed in extensions/manifest |
| Injury clustering (primary/secondary/preexisting) | High | Partial | injury references exist; no canonical cluster contract | Implement `injury_clusters` derived only from diagnosis registry | Cluster table emitted with stable IDs and supporting diagnosis links |
| Provider role classification (`provider_role_registry`) | High | Missing | provider normalization exists but role taxonomy is not explicit | Implement deterministic role mapping (`ER`, `primary_care`, `specialist`, `imaging`, `therapy`, `surgery`) | Role registry emitted before escalation logic; deterministic role tests pass |
| Provider normalization | High | Implemented | `apps/worker/lib/provider_normalize.py`; `pipeline.py` wiring | Reuse | No regressions in provider coverage metrics |
| Encounter deduplication | High | Implemented | `apps/worker/steps/step09_dedup.py` | Reuse | No duplicate encounter inflation in golden packets |
| Treatment gap detection | High | Implemented | `apps/worker/steps/step11_gaps.py` | Reuse | Gap assertions consistent across snapshot/timeline/treatment |

---

## B. Litigation Superiority

| Capability | Competitive Importance | Current Status | Evidence Path | Pass 53 Action | Acceptance Criteria |
|---|---|---|---|---|---|
| Defense attack prediction | Critical | Implemented | `defense_attack_paths`, `defense_attack_map` in pipeline extensions | Reuse and align with new registries | Defense outputs reference canonical registry entities |
| Causation chain clarity | Critical | Partial | causation ladder exists, but no explicit deterministic timeline registry | Add `causation_timeline_registry` with required rungs | Registry present with citation-backed rungs and missing-rung reasons |
| Treatment escalation modeling | High | Partial | escalation concepts present; role-conditioned path not explicit | Add role-driven `treatment_escalation_path` using `provider_role_registry` prerequisite | Escalation path deterministic and role-justified |
| Settlement leverage index | High | Implemented | settlement leverage model in pipeline extensions | Reuse; integrate severity signals | Leverage references injury severity and escalation inputs |
| Injury severity framing per cluster | High | Missing | no typed cluster severity contract | Add `injury_cluster_severity` | Severity includes surgery/injection/MRI findings/treatment duration/PT volume/specialist involvement and feeds leverage model |
| Deposition/Mediation prep structure | Medium | Partial | some litigation sections exist; not fully registry-driven | Use new registries for downstream prep blocks (future pass if needed) | No uncited prep statements on pages 1-5 |

---

## C. Data Contracts and Determinism

| Contract | Current Status | Pass 53 Requirement | Acceptance Test |
|---|---|---|---|
| `visit_abstraction_registry` | Missing | Add typed schema in extensions + manifest | Unit + integration schema checks pass |
| `diagnosis_registry` | Missing | Canonical upstream registry for diagnosis-derived features | Downstream features consume registry only |
| `provider_role_registry` | Missing | Deterministic role taxonomy | Role classification tests pass across case types |
| `injury_cluster_severity` | Missing | Severity model tied to canonical clusters | Deterministic score/rank checks pass |
| `causation_timeline_registry` | Missing | Required rung model with citations | Missing rung -> explicit reason + review policy |
| Encounter-type bucket matrix | Missing | Required buckets vary by encounter type | Matrix defined in `reference/pass_053/encounter_bucket_matrix.md`; PT/ER/specialist/imaging tests pass |

---

## D. Quality Gate Additions

| Gate Rule | Trigger | Expected Status Outcome | Notes |
|---|---|---|---|
| Required bucket completeness threshold violated | Missing required buckets for encounter type above threshold | `needs_review` | No hard fail unless revenue-critical citation invariants break |
| Causation timeline missing required rung(s) when evidence exists | Missing explicit rung with available source evidence | `needs_review` | Include machine-readable reason |
| Registry contract missing/invalid | Missing typed registry in extensions/manifest | `needs_review` | Prevent silent renderer fallback |

---

## E. Non-Spine Coverage Requirement

| Coverage Class | Required for Pass 53 | Status |
|---|---|---|
| Spine complex packet | Yes | Available |
| Spine quick smoke | Yes | Available |
| Non-spine ortho (shoulder/knee) | Yes | Needed for pass validation |
| Neuro/TBI | Recommended next | Gap |

---

## F. Pass 53 Exit Criteria

1. Parity closed on visit abstraction completeness and diagnosis registry clarity.
2. Superiority established with provider-role-driven escalation, explicit causation timeline, and injury cluster severity.
3. All new outputs are typed, deterministic, and citation-backed.
4. Encounter-type-conditioned completeness gates drive `needs_review` when violated.
5. Golden validation includes at least one non-spine packet.

---

## G. Out-of-Scope but Strategic (Pass 54+)

- Outcome dataset capture (`case_resolution_capture`) for long-term settlement intelligence moat:
  - settlement/verdict amount
  - jurisdiction
  - defense firm
  - policy limits
  - mapped medical feature vector

This remains explicitly out of scope for Pass 053 implementation.
