# Pass 064 Plan

## Objective
Validate chronology integrity on richer packets beyond compact MIMIC admissions.

## Validation set
- ED -> imaging -> follow-up packet
- PT course packet
- injection or surgery packet
- mixed prior-history / complex packet

## Acceptance
- clinically distinct phases remain separate
- chronology row count is not artificially collapsed
- no return of junk front-page anchors
- terminal status remains sensible

## Outputs
- `reference/pass_064/summary.json`
- `reference/pass_064/summary.md`
- packet-by-packet chronology notes and artifacts

## If defects appear
- patch the smallest segmentation / projection issue needed
- add focused tests
- rerun the affected packet
