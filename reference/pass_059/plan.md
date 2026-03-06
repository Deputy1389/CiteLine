# Pass 059 Plan

## Objective

Make compact-packet review policy segmentation-aware so pass-58 chronology improvements do not trigger false review downgrades.

## Root Cause

Current shared compact helper:
- `substantive_count <= 3`
- `projection_count <= 3`
- `page_count <= 5`

After pass 58, `Patient_10002930.pdf` now has:
- `chronology_events = 4`
- `projection_entries = 4`
- `page_text_pages = 5`

That is still a compact packet, but it falls out of compact-policy protection.

## Plan

1. Update shared compact policy
- allow small segmented compact packets up to 4 substantive phases / projection rows
- keep page-count ceiling intact

2. Add unit tests for 4-phase compact packets
- AR density soft gate suppressed
- LUQA density/verbatim soft gates suppressed
- wrapper visit-bucket soft gate suppressed

3. Update invariant registry
- add `INV-CP2`

4. Validate locally
- focused gate test slice

5. Validate on cloud
- rerun `Patient_10002930.pdf`
- confirm `success`

## Non-Goals

- no extraction changes
- no renderer changes
- no hard gate changes

## Definition of Done

- segmented compact packet remains within compact-policy protection
- `Patient_10002930.pdf` reruns as `success`
- focused tests pass
