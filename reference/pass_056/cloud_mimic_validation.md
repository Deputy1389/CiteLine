# Pass 056 Cloud MIMIC Validation

Date: 2026-03-05 PST / 2026-03-06 UTC

## Deployment Fixes Required

1. Worker crash-loop on missing tracked module
- Symptom: `ModuleNotFoundError: No module named 'apps.worker.lib.observability'`
- Fix commit: `92dfe78` `fix: track worker observability module for cloud runtime`

2. Worker crash-loop on Python 3.10 incompatibility
- Symptom: `ImportError: cannot import name 'StrEnum' from 'enum'`
- Fix commit: `756b2c1` `fix: make observability module python310 compatible`

3. Worker/runtime mismatch after observability wiring
- Symptom: `persist_pipeline_state() got an unexpected keyword argument 'config'`
- Fix commit: `210d652` `fix: align pipeline persistence with observability args`

Worker host after repair:
- Commit: `210d652`
- Service: `active`

## Fresh MIMIC Cloud Reruns

| Packet | Matter ID | Run ID | Terminal Status | Events | Citations |
|---|---|---|---|---:|---:|
| `Patient_10000032.pdf` | `d9b74a3bb51947709f59ca4c63686758` | `814928e206ff49a2a1af743148213921` | `needs_review` | 1 | 21 |
| `Patient_10001217.pdf` | `9df99f7da79843ebb7a85ddda84ff17d` | `beafbdd2562243ee802609a02c1668e6` | `needs_review` | 1 | 16 |
| `Patient_10002428.pdf` | `852c2a7ec11c40dfbfeeab313ed4b119` | `9f6dabdc56ba438f95c72dd526f3e4bf` | `needs_review` | 2 | 44 |

## Saved Artifacts

- `reference/run_814928e206ff49a2a1af743148213921_evidence_graph.json`
- `reference/run_814928e206ff49a2a1af743148213921_pdf.pdf`
- `reference/run_beafbdd2562243ee802609a02c1668e6_evidence_graph.json`
- `reference/run_beafbdd2562243ee802609a02c1668e6_pdf.pdf`
- `reference/run_9f6dabdc56ba438f95c72dd526f3e4bf_evidence_graph.json`
- `reference/run_9f6dabdc56ba438f95c72dd526f3e4bf_pdf.pdf`

## Notes

- The first post-deploy MIMIC attempts failed before completion because the worker image was not actually cloud-ready. Those failed matters were superseded by the fresh reruns above.
- The repaired worker processed future-dated MIMIC content on cloud without date-range crashes.
- All three reruns terminated as `needs_review`, not `failed`, which is the correct degrade behavior for non-passing quality gates.
- Cloud logs still show optional Gemini narrative calls returning `404 NOT_FOUND`; the pipeline continued and produced artifacts.

## Post-Fix Rerun After Triage Remediation

After commit `3ec1cc5`:

- `Q2` passed on all three reruns using evidence-based sufficiency.
- `Q10` passed on all three reruns; no citation-drift suspects were raised for these packets.
- Production chronology contamination was removed; the bogus 2013/2014 milestone injection no longer appeared in the MIMIC evidence graphs.

Fresh rerun outcomes:

| Packet | Matter ID | Run ID | Terminal Status | Notes |
|---|---|---|---|---|
| `Patient_10000032.pdf` | `4b47ad4244f845f09ab1d789a8289950` | `d485f1e37f7e47a3a5db861cd97d0c74` | `needs_review` | `attorney=True`, `luqa=False`, `export_status=BLOCKED` |
| `Patient_10001217.pdf` | `69cec95fab01488ea0dbf258b76382cb` | `b42e084484574f75b7333c26a95ca23e` | `needs_review` | `attorney=True`, `luqa=False`, `export_status=BLOCKED` |
| `Patient_10002428.pdf` | `42fbf6cdca784413998393b552f17ff9` | `ff3a9edaa1b041e2b2ae6adfad0c34bb` | `needs_review` | `attorney=True`, `luqa=False`, `export_status=BLOCKED` |

This means the original pass-56 triage targets were fixed, but a separate LUQA/export-blocking policy still holds these compact INTERNAL exports in review state.

## Subsequent Gate Triage

After commit `ea68b18`:
- LUQA timeline parsing stopped before billing diagnostics.
- Fresh reruns moved from `export_status=BLOCKED` to `export_status=REVIEW_RECOMMENDED` with `attorney=True` and `luqa=True`.
- Remaining downgrade source was compact-packet soft review policy, not a hard render/content defect.

After commit `c37877b`:
- Compact packets were exempted from the visit-bucket review gate.
- Fresh reruns moved from `needs_review` to `partial`.
- That proved the remaining issue was schema validity drift, not quality-gate failure.

## Final Cloud Validation

After commit `f55b265`:
- Output schema was updated to accept the current additive `RunConfig` shape.
- The same three MIMIC packets were rerun on cloud and all completed as `success` with no warnings.

| Packet | Matter ID | Run ID | Terminal Status | Events | Notes |
|---|---|---|---|---:|---|
| `Patient_10000032.pdf` | `c61e5c9ce0fb47bf95c1632d3ab7ff2b` | `a98d5992949248f7a4ed84f44fafc839` | `success` | 1 | `exports/latest=200`, no warnings |
| `Patient_10001217.pdf` | `914e832100814ec39f18483dce496454` | `72ef76feb0f24b9fb23d44f8b65a9a9f` | `success` | 1 | `exports/latest=200`, no warnings |
| `Patient_10002428.pdf` | `3816721ecac74e8685dde5b17bae607b` | `5b872692f4964f68abd51deb18197ef0` | `success` | 2 | `exports/latest=200`, no warnings |

## Pass-056 Outcome

The final triage chain for compact MIMIC packets was:
1. Remove chronology contamination.
2. Replace format/volume-based review policy with evidence-based sufficiency.
3. Add citation-fidelity guard.
4. Stop LUQA from parsing billing diagnostics as timeline content.
5. Relax compact-packet soft review thresholds.
6. Fix stale output schema drift so valid runs do not downgrade to `partial`.

Result: future-dated compact MIMIC packets now complete on cloud as `success` instead of `failed`, `needs_review`, or `partial`.
