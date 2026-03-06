# OCR Validation Plan

## Purpose
Prove OCR fallback works on scanned or degraded packets instead of inferring health from text-based MIMIC packets that never needed OCR.

## Minimum validation set
- one image-only synthetic packet
- one noisy/OCR-degraded packet from corpus
- one rasterized version of a validated packet

## Acceptance
- terminal completion without crash
- citations still resolve
- provider extraction not polluted by OCR garbage
- chronology remains non-empty and cited

## Output
- batch summary with status counts
- packet-by-packet artifact review notes
