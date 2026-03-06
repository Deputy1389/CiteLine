# Pass 061 Plan

## Objective
Stop synthetic/admin/timing/lab-only events from qualifying as `RendererManifest.top_case_drivers`.

## Scope
- Manifest driver selection only.
- No renderer behavior changes.
- No chronology extraction changes.
- No review-gate changes.

## Files expected
- `apps/worker/steps/step_renderer_manifest.py`
- `tests/unit/test_renderer_manifest.py`
- `governance/invariants.md`
- `reference/pass_061/checklist061.md`
- `reference/pass_061/plan.md`
- `reference/pass_061/top_driver_hygiene_audit.md`

## Implementation steps
1. Audit the current top-driver leak on the pass-60 cloud packet.
2. Add a reusable substantive-driver gate for claim rows.
3. Apply that gate in `_top_case_drivers_from_claim_rows()`.
4. Apply the same gate to `_top_case_driver_fallback_from_events()` so fallback cannot repopulate junk.
5. Register invariant `INV-TD1`.
6. Add focused unit tests for suppression and preservation.
7. Validate locally, then rerun the same cloud packet and inspect `top_case_drivers` plus page-1 top anchors.

## Success signal
- `top_case_drivers` is empty or substantive on the known MIMIC packet.
- The PDF no longer shows synthetic diagnosis labels or record numbers under `Top Record Anchors`.
