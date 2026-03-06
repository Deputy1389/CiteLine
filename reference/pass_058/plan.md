# Pass 058 Plan

## Objective

Preserve clinically meaningful chronology phases so the system behaves like a treatment chronology engine instead of a packet summarizer.

## Problem Statement

Current cloud validation is robust and stable, but batch output shape suggests aggressive event compression:
- `events_total = 1` in 29 of 30 MIMIC reruns
- compression likely occurs across grouping, dedup, and projection merge layers

## Audit Targets

1. `apps/worker/lib/grouping.py`
- contiguous clinical pages are grouped into one block too early

2. `apps/worker/steps/step09_dedup.py`
- multiple merge passes may collapse distinct same-day phases

3. `apps/worker/project/chronology.py`
- projection merge and timeline selection may compress again after extraction

## Plan

1. Build a segmentation audit fixture set
- create controlled packet/event fixtures with ED, imaging, discharge, and procedure phases
- identify where phase collapse occurs

2. Define deterministic phase boundaries
- distinguish duplicates from meaningful phase changes
- likely boundaries: event type, section role, citation separation, source page clusters, and phase-specific content anchors

3. Refactor merge policy
- keep true duplicates merged
- preserve distinct phases even on same day when evidence shows different care moments

4. Add chronology-integrity tests
- ED + discharge remain separate
- discharge + operative note remain separate
- true duplicate fragments still merge
- rerun remains deterministic

5. Validate locally and on cloud
- local unit/integration tests
- rerun selected multi-phase packet(s)

## Non-Goals

- no new renderer logic
- no broad quality-gate recalibration
- no settlement/leverage changes

## Definition of Done

- clinically distinct phases are preserved as separate chronology events
- duplicate suppression still works
- segmentation is deterministic across reruns
- chronology becomes more sequence-faithful without introducing noise explosion
