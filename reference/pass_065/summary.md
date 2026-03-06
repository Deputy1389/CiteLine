# Pass 065 Summary

## Outcome
- Packets validated: 3
- Packets with `office_visit` present: 3
- Packets with reduced `inpatient_daily_note`: 3
- Event counts were preserved across reruns.

## Type Shift
- `05_minor_quick`: `inpatient_daily_note` 3 -> 1; `office_visit` 0 -> 2
- `10_surgical_standard`: `inpatient_daily_note` 6 -> 2; `office_visit` 0 -> 4
- `batch_029_complex_prior`: `inpatient_daily_note` 6 -> 2; `office_visit` 0 -> 4

## Finding
- The system now preserves outpatient/follow-up/PT-eval semantics on richer packets instead of defaulting them to generic inpatient notes.
- No `1900-01-01` sentinel PT date regression appeared in the reruns.
