# Pass 057 Compact Packet Gate Audit

## Scope

Current production downgrade source for the remaining MIMIC batch outlier:
- `reference/pass_056/cloud_batch30_20260305/artifacts/03_Patient_10002930/pipeline_parity_report.json`

Observed failure codes:
- `attorney:AR_FACT_DENSITY_LOW`
- `luqa:LUQA_FACT_DENSITY`
- `visit_bucket_quality:VISIT_BUCKET_REQUIRED_MISSING`

Run shape:
- pages: `5`
- events: `2`
- providers: `2`
- status: `needs_review`
- warning: `export_status=REVIEW_RECOMMENDED, attorney=True, luqa=True`

## Current Gate Logic

### 1. Attorney Readiness compact policy

File:
- `apps/worker/lib/attorney_readiness.py`

Current helper:
- `_is_compact_packet(score_row_count, projection_count, page_count)`
- returns true only when:
  - `score_row_count > 0`
  - `score_row_count <= 3`
  - `projection_count <= 3`
  - `page_count <= 4`

Effect:
- a compact 5-page packet is classified as non-compact and still gets `AR_FACT_DENSITY_LOW`

### 2. LUQA compact policy

File:
- `apps/worker/lib/luqa.py`

Current helper:
- same duplicated `_is_compact_packet(...)` logic
- same `page_count <= 4` cutoff

Effect:
- the same 5-page packet still gets `LUQA_FACT_DENSITY`

### 3. Quality gates wrapper visit-bucket compact policy

File:
- `apps/worker/lib/quality_gates.py`

Current helper:
- `_is_compact_packet_for_quality_gates(projection_count, page_count, total_encounters)`
- current cutoff also treats only very small page-count packets as compact

Effect:
- outlier still receives `VISIT_BUCKET_REQUIRED_MISSING`

## Root Cause

Compact-packet policy is duplicated in three places and is too tight on page count. A short admission/discharge packet with a small number of substantive encounters can exceed four pages without becoming non-compact in any meaningful evidentiary sense.

## Required Refactor

1. Move compact-packet classification into one shared helper.
2. Expand policy to cover compact packets up to five pages when substantive encounter count remains small.
3. Keep suppression limited to soft density and wrapper-level visit-bucket review paths only.
4. Leave hard blockers unchanged.

## Decision Rule For Pass 057

A packet is compact for soft-gate purposes if it has:
- `1-3` substantive encounters or scoreable rows
- `<= 3` projection entries
- `<= 5` pages
- no hard blocker requirement embedded in the gate itself

This is a sufficiency policy, not a blanket waiver.
