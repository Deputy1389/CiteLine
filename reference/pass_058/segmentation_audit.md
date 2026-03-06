# Pass 058 Segmentation Audit

## Observed Signal

From `reference/pass_057/cloud_batch30_rerun_20260306/summary.json`:
- `30/30 success`
- but `events_total = 1` in 29 packets
- and `events_total = 2` in only 1 packet

This indicates the current system is robust at packet completion but likely compressed at the chronology layer.

## Suspected Compression Points

### 1. Clinical grouping is page-contiguity first

File:
- `apps/worker/lib/grouping.py`

Behavior:
- groups contiguous clinical pages into `ClinicalBlock`
- splits only on:
  - non-clinical page
  - page gap
  - source document boundary
  - strong date mismatch
  - explicit provider mismatch

Risk:
- multiple distinct phases within one document can be bundled before extraction even starts.

### 2. Dedup performs three merge passes

File:
- `apps/worker/steps/step09_dedup.py`

Current passes:
1. same `(date, time, provider, event_type)`
2. same source-page overlap
3. same-day same-type/provider-compatible merge

Risk:
- meaningful same-day phases can collapse if provider is unknown, pages overlap, or type is normalized into a mergeable group.

### 3. Projection layer merges again

File:
- `apps/worker/project/chronology.py`

Current behavior:
- projection entries are merged and selected for timeline output
- facts and citations are consolidated downstream of extraction

Risk:
- even correctly extracted multi-event packets can flatten during chronology projection.

## Architectural Hypothesis

The next bottleneck is not extraction failure. It is event segmentation policy drift across three layers:
- grouping
- dedup
- projection merge

The product now survives unusual packets, but it may still compress real treatment sequence into summary nodes.

## Pass 058 Question

When should one packet produce multiple chronology events instead of one summary event?

Required answer shape:
- deterministic
- citation-backed
- phase-aware
- not dependent on case-type-specific keyword hacks
