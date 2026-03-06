# Pass 067 Plan

## Objective

Reduce full-page OCR timeout collapse on rasterized compact scans by adding a deterministic tiled OCR fallback after whole-page timeout.

## Implementation

1. Update `apps/worker/steps/step02_text_acquire.py`
- Keep the existing whole-page DPI retry path.
- If whole-page OCR times out, retry with top-to-bottom tiled OCR on the normalized image.
- Concatenate non-empty tile text deterministically.

2. Add focused unit coverage
- Verify timeout -> tiled fallback -> recovered text.

3. Re-run OCR tests locally
- `tests/unit/test_ocr_utils.py`
- `tests/unit/test_ocr_acquire_text.py`

4. Deploy targeted worker file
- Sync only the OCR file to the worker.
- Rerun the rasterized compact packet.
- Save artifacts in `reference/pass_067/`.

## Success Criteria

- Local OCR tests pass.
- The rasterized validation packet no longer collapses to zero events purely because 4/5 pages timed out at whole-page OCR.
- If cloud still blocks, the new artifact must show whether text recovery improved even if terminal status stays conservative.
