# Pass 063 Plan

## Objective
Validate OCR fallback health on packets that genuinely require OCR.

## Validation set
- one image-only synthetic packet
- one noisy/OCR-degraded packet from corpus
- one rasterized version of a previously validated packet

## Acceptance
- terminal completion without crash
- non-empty citation-backed chronology output
- explicit OCR metrics recorded
- provider/event extraction not obviously polluted by OCR garbage

## Outputs
- `reference/pass_063/summary.json`
- `reference/pass_063/summary.md`
- packet-by-packet artifacts and review notes

## If defects appear
- patch only the smallest OCR-path defect needed
- add focused tests for that defect
- rerun the affected OCR packet
