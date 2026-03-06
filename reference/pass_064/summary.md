# Pass 064 Summary

## Outcome
- Packets validated: 4
- Event count range: 8 to 14
- Mean events_total: 10.5
- Packets containing `1900-01-01` after PT fix: 1

## Packet Results
- `05_minor_quick` -> `needs_review`; `events=8`; `pages_ocr=0`; `event_types={'inpatient_daily_note': 3, 'imaging_study': 1, 'hospital_discharge': 1, 'billing_event': 1, 'discharge': 1, 'pt_visit': 1}`
- `08_soft_tissue_noisy` -> `needs_review`; `events=9`; `pages_ocr=3`; `event_types={'pt_visit': 1, 'inpatient_daily_note': 4, 'imaging_study': 1, 'hospital_discharge': 1, 'billing_event': 1, 'discharge': 1}`
- `10_surgical_standard_after_pt_fix` -> `needs_review`; `events=14`; `pages_ocr=17`; `event_types={'inpatient_daily_note': 6, 'imaging_study': 1, 'procedure': 1, 'hospital_discharge': 2, 'pt_visit': 2, 'billing_event': 1, 'discharge': 1}`
- `batch_029_complex_prior_after_pt_fix` -> `needs_review`; `events=11`; `pages_ocr=3`; `event_types={'inpatient_daily_note': 6, 'imaging_study': 1, 'pt_visit': 1, 'hospital_discharge': 1, 'billing_event': 1, 'discharge': 1}`

## Finding
- Chronology integrity is materially better on richer packets; the system is no longer behaving like a one-event summarizer on this slice.
- PT aggregate sentinel dates were removed from the evidence graph.
- Remaining bottleneck: too many clinically distinct encounters are still typed as `inpatient_daily_note` instead of more specific encounter phases.
