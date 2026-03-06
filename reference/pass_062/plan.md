# Pass 062 Plan

## Objective
Add a deterministic `Case Skeleton` Page-1 fallback for sparse packets so lawyers get immediate orientation when no top anchors qualify.

## Scope
- Extend `RendererManifest` with typed `case_skeleton`
- Build skeleton from existing events/citations/bucket evidence only
- Render skeleton on Page 1 when `top_case_drivers == []`
- Add sitrep follow-on docs for OCR validation, richer chronology validation, and launch scope

## Out of scope
- No extraction changes
- No AI-generated narrative
- No quality-gate threshold changes
- No launch-copy rewrite in app UI

## Files expected
- `packages/shared/models/domain.py`
- `apps/worker/steps/step_renderer_manifest.py`
- `apps/worker/steps/export_render/timeline_pdf.py`
- `tests/unit/test_renderer_manifest.py`
- `tests/unit/test_pdf_quality_gate.py`
- `governance/invariants.md`
- `reference/pass_062/*`

## Validation
- `python -m pytest -q tests/unit/test_renderer_manifest.py tests/unit/test_pdf_quality_gate.py tests/unit/test_mediation_sections.py`
- focused artifact/PDF inspection after local render

## Follow-on docs from sitrep
- OCR validation plan
- rich chronology validation plan
- narrow-pilot launch scope recommendation
