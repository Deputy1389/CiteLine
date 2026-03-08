# Pass 121 Summary

## Outcome

Live packet smoke completed against the currently deployed `www.linecite.com` path.

- Packets attempted: `2`
- Terminal runs: `2`
- Terminal status mix: `2 needs_review`, `0 success`, `0 failed`
- Artifact retrieval:
  - `exports_latest.json`: `2/2`
  - `evidence_graph.json`: `2/2`
  - `chronology.pdf`: `2/2`

## Packets

### orthopedic_shoulder_seed41

- Uploaded artifact: clean PDF
- Matter: `37fdd1826d9b40e595b6a9ca7ce2935d`
- Run: `ba1d3ee806124f12b074dc9e239399da`
- Status: `needs_review`
- Metrics:
  - `49` pages
  - `0` OCR pages
  - `22` events total
  - `21` events exported
  - `41` providers
  - `8.74s` processing time
- Warnings:
  - `LITIGATION_REVIEW_FAIL`
  - `QUALITY_GATE_FAILED`

### ocr_rasterized_seed41

- Uploaded artifact: rasterized scan PDF
- Matter: `6fc3aac4b7af4491b7aeb78476b8dc7e`
- Run: `eaceb85d47f0435586ac1a66c88284fc`
- Status: `needs_review`
- Metrics:
  - `15` pages
  - `15` OCR pages
  - `9` events total
  - `9` events exported
  - `36` providers
  - `184.84s` processing time
- Warnings:
  - `QUALITY_GATE_FAILED`

## Artifact Paths

- Batch summary JSON: [cloud_validation_summary.json](C:/Citeline/reference/pass_121/cloud_batch/cloud_validation_summary.json)
- Batch summary Markdown: [cloud_validation_summary.md](C:/Citeline/reference/pass_121/cloud_batch/cloud_validation_summary.md)
- Clean packet cloud run: [orthopedic_shoulder_seed41](C:/Citeline/reference/pass_121/cloud_batch/cloud_runs/orthopedic_shoulder_seed41)
- Scan packet cloud run: [ocr_rasterized_seed41](C:/Citeline/reference/pass_121/cloud_batch/cloud_runs/ocr_rasterized_seed41)

## Honest Read

This proves the currently deployed live system can still ingest and process:

- a small clean packet
- a small scan-heavy packet that requires OCR on every page

This does **not** prove the new direct-upload path or periodic orphan sweeper are live in production.

Reason:
- Render deploys from GitHub `main`
- this workspace has local upload/sweeper changes that are not yet proven to be on the deployed branch
- the smoke harness used the currently deployed `/api/citeline/matters/{matterId}/documents` path

So the correct conclusion is:

- current production ingestion works for small packets
- current production OCR handling works on a hostile small scan packet
- live rollout status for Passes `117-120` remains unproven until deployed and re-smoked
