# Pass 060 Plan

## Objective
Add a deterministic semantic hygiene floor to `RendererManifest.promoted_findings` so Page 1 only elevates citation-backed substantive findings, not synthetic/admin boilerplate.

## Scope
- Pipeline-side manifest selection only.
- No renderer keyword logic.
- No broad claim-ledger redesign.
- No quality-gate threshold changes.

## Files expected
- `apps/worker/steps/step_renderer_manifest.py`
- `tests/unit/test_renderer_manifest.py`
- `reference/pass_060/checklist060.md`
- `reference/pass_060/plan.md`
- `reference/pass_060/promotion_hygiene_audit.md`
- `governance/invariants.md`

## Implementation steps
1. Audit current promoted finding pollution classes from the pass-59 MIMIC artifact.
2. Add reusable semantic hygiene helpers in `step_renderer_manifest.py` for:
   - synthetic generic diagnoses
   - administrative record identifiers
   - pure admit/discharge timestamp lines
   - low-value treatment/admin boilerplate
3. Apply the hygiene guard only in the claim-row promotion path.
4. Preserve substantive diagnosis/imaging/objective/procedure claims.
5. Register invariant `INV-PF1`.
6. Add focused tests for suppression and preservation.
7. Rebuild/inspect the known MIMIC artifact to confirm promoted-finding count and quality improve deterministically.

## Validation
- `python -m pytest -q tests/unit/test_renderer_manifest.py`
- Artifact inspection on `reference/pass_059/cloud_rerun_patient_10002930/evidence_graph.json`

## Success signal
- The known MIMIC artifact no longer promotes record numbers, generic `Medical Condition` diagnosis labels, or admit/discharge timestamp boilerplate.
- Substantive promoted findings remain intact.
