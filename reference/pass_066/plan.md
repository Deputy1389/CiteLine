# Pass 066 Plan

## Objective

Convert passes 57, 62, 63, 64, and 65 into a single reproducible launch-readiness contract so narrow-pilot readiness and broad-launch blockers are machine-readable.

## Implementation

1. Add `scripts/build_launch_acceptance_matrix.py`
- Read the existing pass artifacts:
  - `reference/pass_057/cloud_batch30_rerun_20260306/summary.json`
  - `reference/run_c0e611f937cf4292a328ada3cf57d74b_evidence_graph.json`
  - `reference/pass_063/summary.json`
  - `reference/pass_064/summary.json`
  - `reference/pass_065/summary.json`
- Derive readiness dimensions:
  - compact text-backed packet success
  - sparse packet Page-1 orientation fallback
  - OCR degraded packet health
  - fully rasterized scan readiness
  - richer chronology/encounter semantics
  - coverage breadth

2. Generate pass outputs
- `reference/pass_066/launch_acceptance_matrix.json`
- `reference/pass_066/launch_readiness.md`

3. Add a unit test
- Validate that the generator marks narrow pilot ready and broad launch blocked when OCR/corpus breadth remain unresolved.

4. Update the invariant registry
- Add `INV-LA1` in `governance/invariants.md`

## Success Criteria

- Current validated slice resolves to:
  - `narrow_pilot_ready = true`
  - `broad_launch_ready = false`
- Blocking reasons are explicit and artifact-backed.
- The verdict is reproducible from the stored pass artifacts.
