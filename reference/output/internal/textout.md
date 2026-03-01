# Pass33 Gold Run — INTERNAL Export
**Date**: 2026-02-28
**Packets**: 05_minor_quick, batch_029_complex_prior
**Mode**: INTERNAL (both runs)
**Run IDs**: pass33-minor-quick-internal, pass33-batch029-internal

---

## Results Summary

| Packet | overall_pass | luqa | attorney | legal | entries | anchor | strategy |
|---|---|---|---|---|---|---|---|
| 05_minor_quick | PASS | 100 | 100 | 100 | 4 | null (no specials) | ANCHOR_NEAR_SPECIALS |
| batch_029_complex_prior | PASS | 97 | 100 | 97 | 9 | null (no specials) | STANDARD |

Zero regression deltas vs MEDIATION gold run (pass33-minor-quick / pass33-batch029).

---

## internal_demand_package Verification

Both packets confirmed populated:

```
05_minor_quick/evidence_graph.json   → export_mode: INTERNAL
                                       internal_demand_package: PRESENT
                                       schema_version: internal_demand_package.v1
                                       mode: INTERNAL_ONLY_DO_NOT_EXPORT

batch_029_complex_prior/evidence_graph.json → export_mode: INTERNAL
                                              internal_demand_package: PRESENT
                                              schema_version: internal_demand_package.v1
                                              mode: INTERNAL_ONLY_DO_NOT_EXPORT
```

---

## Multiplier Engine Output

### 05_minor_quick

| Field | Value |
|---|---|
| base_band | [2.5, 4.5] (disc/radic tier) |
| adjustments | pt_visits_lt_6 (down, −0.5) |
| adjusted_band | [2.0, 4.0] |
| strength_band | LOW |
| confidence_score_0_100 | 25 |
| strategy | ANCHOR_NEAR_SPECIALS |
| anchor | null (no specials computed in eval path) |
| primary_drivers | [] |
| primary_risks | pt_visits_lt_6 |

### batch_029_complex_prior

| Field | Value |
|---|---|
| base_band | [2.5, 4.5] (disc/radic tier from radiculopathy) |
| adjustments | major_gap_in_care_gt_120_days (down, −1.0), radiculopathy_documented (up, +1.0) |
| adjusted_band | [2.0, 4.0] (net flat) |
| strength_band | MODERATE |
| confidence_score_0_100 | 39 (CSI=69: 69×0.6=41.4 + 1×6 − 1×8 = 39.4 → 39) |
| strategy | STANDARD |
| anchor | null (no specials computed in eval path) |
| confidence_drivers_ranked | [radiculopathy_documented, weight=1.0] |

**Note**: anchor is null in both packets because the eval path (run_case.py / eval_sample_172.py)
does not compute billing specials. In production (pipeline.py), specials flow from step17 and
anchor + counteroffer classifier are fully populated.

---

## INTERNAL PDF

Both PDFs include:
- Full chronology timeline with "INTERNAL ANALYTICS — NOT FOR EXTERNAL DISTRIBUTION" footer
- Settlement Posture appendix page (INTERNAL-only section rendered by orchestrator)
- All valuation/settlement extension data present (not stripped)

PDF sizes:
- 05_minor_quick/output_INTERNAL.pdf: 25 KB
- batch_029_complex_prior/output_INTERNAL.pdf: 41 KB

---

## Fix Applied This Run

`scripts/eval_sample_172.py` was missing the `build_internal_demand_package` call.
The call exists in `apps/worker/pipeline.py` (production path) but was not mirrored
in the eval path. Added after the `settlement_model_report` block:

```python
from apps.worker.lib.internal_demand_copilot import build_internal_demand_package
graph.extensions["internal_demand_package"] = build_internal_demand_package(
    evidence_graph=graph.model_dump(mode="json"),
    csi_internal=_csi,
    damages_structured=None,  # specials not computed in eval path
)
```

---

## Files in This Directory

```
reference/output/internal/
├── textout.md                              ← this file
├── 05_minor_quick/
│   ├── output_INTERNAL.pdf               ← INTERNAL PDF (settlement posture page included)
│   ├── evidence_graph.json               ← INTERNAL artifact (internal_demand_package present)
│   ├── scorecard.json
│   ├── luqa_report.json
│   ├── attorney_readiness_report.json
│   └── pipeline_parity_report.json
└── batch_029_complex_prior/
    ├── output_INTERNAL.pdf
    ├── evidence_graph.json
    ├── scorecard.json
    ├── luqa_report.json
    ├── attorney_readiness_report.json
    └── pipeline_parity_report.json
```
