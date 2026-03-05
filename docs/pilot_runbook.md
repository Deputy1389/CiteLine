# Pilot Runbook

## On Packet Submission
1. Check run status via `GET /api/citeline/runs/{run_id}`.
2. Check worker logs for errors/timeouts.
3. Verify core artifacts exist:
- `evidence_graph.json`
- `chronology.pdf`
- `missing_records.csv`
4. Confirm `GET /api/citeline/matters/{matter_id}/exports/latest?export_mode=INTERNAL` returns `200`.
5. Download outputs and attach to case notes.

## Common Failures

### OCR Failure
Signal: low text yield, high garbage pages, extraction sparse.
Action:
- Confirm OCR fallback fired in worker logs.
- Mark run `needs_review` and rerun once.
- Escalate packet for manual preprocessing if repeated.

### Extraction Mismatch
Signal: expected encounters/findings missing or misgrouped.
Action:
- Compare `evidence_graph.json` events vs rendered chronology rows.
- Verify citations present and page numbers valid.
- File extraction bug with packet/page references.

### Missing Sections
Signal: required PDF section is blank or absent.
Action:
- Validate source events exist in evidence graph.
- Validate renderer manifest (`extensions.renderer_manifest`) has required fields.
- Rerun after patch only if deterministic root cause identified.

### Webhook Failure
Signal: run completes but callback not delivered.
Action:
- Confirm run terminal status in API.
- Retry webhook delivery from queue/retry script.
- If retries fail, notify pilot user with direct export links.

### Export Generation Failure
Signal: artifacts missing, PDF not produced, or `exports/latest` not available.
Action:
- Check artifact persistence logs.
- Regenerate export from run artifacts if possible.
- If not possible, rerun packet and mark incident.

## Response Templates
- "Thanks — this appears to be an OCR issue on page {page}. We are patching extraction and rerunning now."
- "We found a citation/render mismatch in this packet. We are rerunning with a fix and will send updated exports shortly."
- "The run completed but delivery callback failed. We are retrying notification and sharing direct artifacts now."

## Escalation Rules
- Any placeholder leak on pages 1-3 -> force `needs_review`.
- Any uncited statement on pages 1-5 -> block export and escalate.
- Conflicting visit counts -> `needs_review` with reconciliation note.
