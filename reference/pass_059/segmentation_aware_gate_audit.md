# Pass 059 Segmentation-Aware Gate Audit

## Target Artifact

- `reference/pass_058/cloud_rerun_patient_10002930/pipeline_parity_report.json`

## Observed State After Pass 58

Packet:
- `Patient_10002930.pdf`

Status:
- `needs_review`

Metrics:
- `pages_total = 5`
- `events_total = 4`
- `events_exported = 4`

Failure codes:
- `attorney:AR_FACT_DENSITY_LOW`
- `luqa:LUQA_FACT_DENSITY`
- `visit_bucket_quality:VISIT_BUCKET_REQUIRED_MISSING`

## Why This Happened

Pass 58 improved chronology integrity by splitting one compressed packet into four clinically distinct events. The review gates still rely on Pass 57 compact policy, which treats compact packets as:
- `substantive_count <= 3`
- `projection_count <= 3`
- `page_count <= 5`

That means the packet became more faithful but lost compact-policy suppression.

## Architectural Conclusion

The next fix is not another segmentation change.
It is policy alignment:
- segmentation-aware compact packets must stay compact for soft-gate purposes
- otherwise chronology integrity and quality policy work against each other

## Required Refactor

Update the shared compact helper so small segmented packets can preserve up to four phases while still being treated as compact for AR/LUQA/wrapper soft gates.
