# Pass33 Gold Run — textout.md
**Date**: 2026-02-28
**Packets**: 05_minor_quick, batch_029_complex_prior
**Mode**: MEDIATION (both runs)
**Run IDs**: pass33-minor-quick, pass33-batch029

---

## Results Summary

| Packet | overall_pass | qa_pass | luqa | attorney | legal | entries | gaps |
|---|---|---|---|---|---|---|---|
| 05_minor_quick | ✅ PASS | ✅ | 100 | 100 | 100 | 4 | 0 |
| batch_029_complex_prior | ✅ PASS | ✅ | 97 | 100 | 97 | 9 | 2 |

No hard failures. No placeholder leaks. No banned valuation tokens. No `internal_demand_package`
in either MEDIATION evidence_graph.json. Zero regression deltas on entry counts, QA scores,
claim signatures, and fragility IDs vs prior runs (pass32-minor-quick, pass32-batch029-fix).

---

## Pass33 Strip Verification

**Both packets confirmed clean:**

```
05_minor_quick/evidence_graph.json           → "export_mode": "MEDIATION"
                                               internal_demand_package: NOT PRESENT ✅

batch_029_complex_prior/evidence_graph.json  → "export_mode": "MEDIATION"
                                               internal_demand_package: NOT PRESENT ✅
```

The dual-strip defense worked on first run — no leak debugging required.

---

## What Pass33 Added (Internal Layer Only)

Pass33 adds one new extension key: `extensions.internal_demand_package`.
It fires in the pipeline for every run mode. The MEDIATION serializer strips it in two places:
- `_VALUATION_EXTENSION_KEYS` in `artifacts_writer.py`
- `_MEDIATION_BANNED_KEYS` in `orchestrator.py`

The internal package is built from:
- `settlement_feature_pack` (existing, already extracted before the call)
- `case_severity_index` (existing, already computed before the call)
- `specials_summary` payload

**No new extraction. No LLM. No gate mutations.**

---

## What the Internal Demand Package Produces

### Multiplier Engine

| Component | Description |
|---|---|
| `base_band` | From CSI intensity/objective tier: surgery→[5.5,9.0], injection→[3.5,6.0], disc/radic→[2.5,4.5], soft tissue→[2.0,3.5], default→[1.5,2.5] |
| `adjustments` | 10 upward + 7 downward factors, ±0.5/1.0 steps, ±2.0 caps, each with citation_ids slot |
| `adjusted_band` | base_band ± net adjustment, floored at [1.0,2.0], surgery floored at [5.0,8.0] |
| `anchor` | `specials × (low + percentile*(high-low))`, rounded $100, floor at `specials*(low+0.25)` |

Anchor percentile by risk_count: 0 risks → 90th, 1 risk → 80th, ≥2 risks → 70th.
Anchor is `null` when specials are absent — no phantom math.

### Guards Applied (from tightening pass)

- `imaging_negative_or_minor` suppressed when radiculopathy/disc documented or escalation present
- `pt_visits_lt_6` suppressed when injection/surgical tier or specialist active
- Surgery floor preserved at [5.0, 8.0] even under maximum downward pressure
- Anchor floor safety: `anchor ≥ specials * (low + 0.25)` prevents under-anchoring in tight bands
- Counteroffer classifier is band-tied: LOWBALL / BELOW_RANGE / NEGOTIABLE / STRONG_OFFER / ABOVE_EXPECTATION

### Case Strength Formula

```python
confidence_score = clamp(csi_score_0_100 * 0.6 + up_count * 6 - risk_count * 8, 0, 100)
# CSI dominates (60%); adjustments refine, not override
```

Bands: LOW (0–30), MODERATE (31–55), STRONG (56–75), HIGH (76–100).

### Negotiation Strategy Map

6-entry deterministic lookup table. Same inputs → same output every call. Examples:
- STRONG + 0 risks → `PUSH_HIGH_ANCHOR`
- STRONG + 1 risk → `ASSERTIVE_WITH_PREEMPTION`
- STRONG + 2+ risks → `STANDARD_WITH_REBUTTAL`
- LOW → `ANCHOR_NEAR_SPECIALS`

### Demand Letter Draft

Template-driven, 6 blocks (A–F). All content from existing pipeline signals.
Hard constraints enforced in template (not optional):
- No verdict prediction language
- No "permanent injury/disability" unless documented permanency in structured evidence
- No multiplier values, no CSI scores
- Block F template-locked opening: "Based on the documented objective findings…"
- Block F omitted when anchor is null

Entire draft labeled: `INTERNAL DRAFT — DO NOT EXPORT — EDIT BEFORE SENDING`

### Confidence Drivers Ranked

`strength_summary.confidence_drivers_ranked` ranks top-3 value drivers by adjustment delta.
Attorneys see: "These are the top things driving this case's value."

---

## Deterministic Parity Confirmation

Both packets showed `entry_count_delta: 0`, `qa_score_delta: 0`, `new_claim_ids_count: 0`
vs prior runs. All chronology row counts, QA scores, and gate outcomes unchanged.

Pass33 adds internal intelligence only. It does not touch the renderer, projection pipeline,
gate logic, or any existing output field.

---

## Tests — 56 Tests, All Passing

New file: `tests/unit/test_internal_demand_copilot.py`

Coverage:
- **Base band** (8): surgery, injection, disc, radiculopathy, soft tissue, no CSI, no objective, surgical objective
- **Adjustments** (13): single up, single down, combined math, up cap, down cap, surgery floor, global floor, 365d non-additive, imaging_negative guard (×2), pt_visits_lt6 guard (×2), pt_visits_lt6 applies
- **Anchor** (7): percentile 0/1/2+, $100 rounding, null when no specials, floor safety, upper clamp
- **Schema** (4): schema_version, mode tag, adjustments sorted, citation_ids present
- **Strip** (4): MEDIATION excludes key, INTERNAL keeps key, _VALUATION_EXTENSION_KEYS check, _MEDIATION_BANNED_KEYS check
- **Strategy map** (5): deterministic, LOW→ANCHOR_NEAR_SPECIALS, STRONG+0→PUSH_HIGH, STRONG+2→REBUTTAL, MODERATE+2→BUILD_CASE
- **Counteroffer** (6): LOWBALL, BELOW_RANGE, NEGOTIABLE, STRONG_OFFER, ABOVE_EXPECTATION, UNKNOWN when no specials
- **Demand letter safety** (4): F absent w/o specials, F absent w/ zero specials, no verdict language, INTERNAL DRAFT label
- **Confidence drivers** (2): weights match deltas, at most 3 ranked
- **Integration smoke** (3): no exception on empty inputs, anchor present when specials provided, full MEDIATION strip round-trip

All 108 Pass32 unit tests remain green. No existing tests broken.

---

## Files Changed (Pass33)

| File | Change |
|---|---|
| `apps/worker/lib/internal_demand_copilot.py` | **NEW** — 330 lines |
| `apps/worker/pipeline.py` | +1 import, +5 lines to call after settlement_model_report |
| `apps/worker/lib/artifacts_writer.py` | Add `"internal_demand_package"` to `_VALUATION_EXTENSION_KEYS` |
| `apps/worker/steps/export_render/orchestrator.py` | Add `"internal_demand_package"` to `_MEDIATION_BANNED_KEYS` |
| `tests/unit/test_internal_demand_copilot.py` | **NEW** — 56 tests |

---

## Files in This Directory

```
reference/output/
├── textout.md                              ← this file
├── 05_minor_quick/
│   ├── output_MEDIATION.pdf               ← rendered mediation PDF
│   ├── evidence_graph.json                ← MEDIATION artifact (internal_demand_package stripped)
│   ├── scorecard.json                     ← QA scores + confidence tier
│   ├── luqa_report.json                   ← LUQA gate detail
│   ├── attorney_readiness_report.json     ← attorney readiness gate
│   └── pipeline_parity_report.json        ← parity contract snapshot
└── batch_029_complex_prior/
    ├── output_MEDIATION.pdf
    ├── evidence_graph.json
    ├── scorecard.json
    ├── luqa_report.json
    ├── attorney_readiness_report.json
    └── pipeline_parity_report.json
```
