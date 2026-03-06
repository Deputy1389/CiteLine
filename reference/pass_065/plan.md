# Pass 065 Plan

## Objective
Refine event typing for richer packets so chronology preserves clinically meaningful phases instead of defaulting to `inpatient_daily_note`.

## Scope
- audit phase/type assignment in clinical extraction and assembler layers
- patch the smallest deterministic typing rule set needed
- add focused unit tests
- rerun richer cloud packets and inspect event-type mix

## Acceptance
- fewer clinically-distinct phases typed as `inpatient_daily_note`
- no loss of event count integrity from pass 064
- no sentinel PT date regression

## Outputs
- `reference/pass_065/encounter_typing_audit.md`
- `reference/pass_065/summary.json`
- `reference/pass_065/summary.md`
