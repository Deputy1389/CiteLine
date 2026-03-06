# Top Driver Hygiene Audit

## Evidence Source
- `reference/run_e9f43b7cb1d44961b65bf6b50a3bb262_evidence_graph.json`
- `reference/run_e9f43b7cb1d44961b65bf6b50a3bb262_pdf.pdf`

## Observed failure
`renderer_manifest.top_case_drivers` contains event IDs whose linked claim rows are dominated by:
- synthetic diagnosis labels (`Medical Condition ...`)
- administrative record identifiers (`ADMISSION RECORD: #...`)
- admit/discharge timestamp boilerplate
- lab panel lines

## Why pass 060 did not fix it
Pass 060 guarded `promoted_findings`, but `top_case_drivers` uses a separate selector:
- `_top_case_drivers_from_claim_rows()`
- `_top_case_driver_fallback_from_events()`

The renderer is not the cause here. `timeline_pdf.py` reads `top_case_drivers` in manifest-only mode.

## Required fix
- Reuse the same low-value semantic classes from pass 060.
- Require at least one substantive driver assertion per selected event.
- Prefer an empty `top_case_drivers` list over junk anchors.
