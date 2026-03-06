# Promotion Hygiene Audit

## Evidence Source
- `reference/pass_059/cloud_rerun_patient_10002930/evidence_graph.json`

## Observed pollution classes

1. Synthetic generic diagnosis labels
- Example: `PRIMARY DIAGNOSIS: Medical Condition B20`
- Problem: citation-backed but not attorney-meaningful; this is synthetic placeholder taxonomy, not a useful injury diagnosis.

2. Administrative record identifiers
- Example: `ADMISSION RECORD: #22380825`
- Problem: operational metadata promoted as a case finding.

3. Pure admit/discharge timestamp lines
- Example: `ADMITTED: 2200-06-05 05:43:00 | DISCHARGED: 2200-06-05 10:26:00`
- Problem: chronology timing belongs in the timeline, not as a Page-1 promoted medical finding.

4. Boilerplate discharge/treatment summaries with no elevated legal value
- Example: synthetic discharge summary lines and low-value treatment/admin text.
- Problem: these inflate promoted finding count and bury higher-value items.

## Root cause
`_promoted_findings_from_claim_rows()` currently promotes any cited claim row after minimal cleanup. It infers category from claim type but does not enforce a semantic quality floor before creating `PromotedFinding` items.

## Required guard behavior
- Allow: substantive diagnosis, imaging pathology, objective deficits, procedures, and meaningful treatment findings.
- Suppress: synthetic generic labels, admin identifiers, timing-only rows, and weak boilerplate treatment lines.

## Non-goals
- Do not re-rank renderer output in the renderer.
- Do not weaken citation requirements.
- Do not redesign claim extraction in this pass.
