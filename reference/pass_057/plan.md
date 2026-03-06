# Pass 057 Plan

## Objective

Recalibrate compact-packet production quality gates so short citation-backed admission/discharge packets are not downgraded solely for low prose density or generic required-bucket misses.

## Target

Primary target packet class:
- compact packets with 1-3 substantive encounters
- low page count but possibly slightly above the current 4-page compact cutoff
- no hard integrity blockers

Acceptance target packet for this pass:
- `Patient_10002930.pdf`
- current cloud outlier from `reference/pass_056/cloud_batch30_20260305/artifacts/03_Patient_10002930/`

## Plan

1. Introduce a shared compact-packet policy helper
- create one helper used by AR, LUQA, and quality-gates wrapper
- classify packets by substantive encounter count, projection count, and page-count ceiling tuned for compact admission/discharge packets

2. Replace duplicated local compact heuristics
- `apps/worker/lib/attorney_readiness.py`
- `apps/worker/lib/luqa.py`
- `apps/worker/lib/quality_gates.py`

3. Add unit coverage for the 5-page compact outlier shape
- prove that soft density and visit-bucket review gates suppress for compact citation-backed packets
- preserve existing non-compact threshold behavior

4. Update invariant registry
- add `INV-CP1`

5. Validate locally
- focused unit tests for AR, LUQA, and wrapper

6. Validate on cloud
- deploy updated worker
- rerun `Patient_10002930.pdf`
- confirm terminal status flips from `needs_review` to `success`

## Non-Goals

- no renderer changes
- no extraction changes
- no changes to hard integrity blockers
- no broader leverage or settlement logic edits

## Definition of Done

- one shared compact-packet policy is used in all three gate layers
- `Patient_10002930.pdf` reruns as `success`
- no new hard-block regressions in focused unit tests
