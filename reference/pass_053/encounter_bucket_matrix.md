# Pass 053 Encounter Bucket Matrix

## Purpose
Define encounter-type-conditioned required buckets to prevent false `needs_review` triggers while preserving abstraction quality.

Rule semantics:
- `Required`: must be present or explicitly missing with reason.
- `Conditional`: required only if evidence type is present in source text.
- `Optional`: include when available; absence does not fail completeness.

---

## Bucket Definitions

- `complaints`
- `objective_findings`
- `diagnostics`
- `diagnoses`
- `treatments`
- `prescriptions_or_referrals`
- `functional_limitations`
- `causation_statements`

---

## Encounter-Type Matrix (v1)

| Encounter Type | complaints | objective_findings | diagnostics | diagnoses | treatments | prescriptions_or_referrals | functional_limitations | causation_statements |
|---|---|---|---|---|---|---|---|---|
| `ER` | Required | Required | Conditional | Required (or impression) | Required | Conditional | Conditional | Conditional |
| `primary_care` | Required | Conditional | Conditional | Required | Required (plan acceptable) | Conditional | Conditional | Conditional |
| `specialist` | Required | Required (or exam findings) | Conditional | Required | Required | Conditional | Conditional | Conditional |
| `imaging` | Optional | Optional | Required | Conditional | Optional | Optional | Optional | Optional |
| `therapy` (`PT`) | Required | Conditional | Optional | Optional | Required | Optional | Required | Optional |
| `surgery` / operative | Required (or pre-op indication) | Required (intra/post-op findings acceptable) | Conditional | Required | Required | Conditional | Conditional | Conditional |
| `follow_up` generic | Required | Conditional | Optional | Conditional | Required (plan acceptable) | Conditional | Conditional | Optional |

---

## Completeness Evaluation Rules

1. Evaluate completeness per encounter against its row in the matrix.
2. Any missing `Required` bucket must emit:
   - `missing_bucket_code`
   - `encounter_id`
   - `reason`
   - `citation_context_present` boolean
3. `Conditional` buckets become required only if supporting evidence class exists in source extraction.
4. A run degrades to `needs_review` when configured threshold is exceeded:
   - `missing_required_bucket_ratio > threshold`
   - or `missing_required_bucket_count >= hard_count_threshold`

---

## False Positive Protections

- PT visits do not require diagnosis by default.
- Imaging encounters do not require complaints/treatment by default.
- Follow-up administrative notes can satisfy treatment bucket via documented plan when direct intervention absent.

---

## Determinism Requirements

- Encounter type classification must be deterministic from structured inputs.
- Bucket ordering and serialization keys are stable.
- Re-running same packet/config must produce identical completeness outcomes.

---

## Test Requirements (Pass 053)

- PT visit without diagnosis does not fail completeness.
- ER visit missing treatment fails completeness.
- Imaging-only encounter with diagnostics passes completeness.
- Specialist visit with exam + diagnosis + plan passes completeness.
- Determinism test: repeated runs produce identical bucket status and hash.
