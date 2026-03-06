# Pass 065 Encounter Typing Audit

## Observed problem
Pass 064 improved chronology row counts, but richer packets still overused `inpatient_daily_note` for clinically distinct outpatient/follow-up/PT-style encounters.

## Concrete mis-typings
- `05_minor_quick`: PT-eval style page with `Elite Physical Therapy`, `Functional Status`, and `Range of Motion` was typed as `inpatient_daily_note`.
- `10_surgical_standard_after_pt_fix`: `ASSESSMENT AND TREATMENT PLAN` / `TREATMENT PLAN DISCUSSION` block with modified-duty follow-up language remained `inpatient_daily_note`.
- `batch_029_complex_prior_after_pt_fix`: orthopedic/PT follow-up blocks were typed as `inpatient_daily_note` despite explicit outpatient care cues.

## Root cause
- `detect_encounter_type()` already recognized some outpatient/PT signals, but `PRIORITY_MAP` ranked `inpatient_daily_note` above `office_visit`, so generic inpatient typing would win once a block started.
- Several high-signal outpatient phrases were not in the office/PT cue sets.

## Refactor
- Increase `office_visit` priority above `inpatient_daily_note` while preserving existing phase locks for ED/admission/discharge/procedure.
- Expand outpatient/PT cues with:
  - `functional status`
  - `manual therapy`
  - `home exercise program`
  - `treatment plan discussion`
  - `modified duty`
  - `work status`
  - `return to work`
  - specialist follow-up terms such as `orthopedic`, `pain management`, `neurosurgery`, `physiatry`

## Expected effect
- PT-eval and specialist follow-up blocks upgrade to `office_visit`.
- Existing hard phase types remain locked.
- Chronology row counts remain stable while event semantics improve.
