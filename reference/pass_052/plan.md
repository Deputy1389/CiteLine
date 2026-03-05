# Pass 052 Plan - 48h Stabilization Execution

## Scope
Pilot-readiness stabilization only. No new product features.

## Execution Steps

1. Wire explicit quality policy
- Add `quality_mode: Literal["strict", "pilot"] = "strict"` to `RunConfig`.
- Add `quality_mode` to API `CreateRunRequest` defaults and persisted run config.
- Thread `quality_mode` into production pipeline quality gate call and eval `run_case` call.

2. Implement pilot-mode gate behavior
- Update `apps/worker/lib/quality_gates.py` classification to accept `quality_mode`.
- In `pilot` mode: demote `LUQA_META_LANGUAGE_BAN` to soft (review required, not blocked).
- In `strict` mode: preserve existing hard behavior.

3. Add regression tests
- Extend `tests/unit/test_quality_gates_wrapper.py` for strict vs pilot behavior.
- Run focused unit tests for quality gate wrapper and run-case wiring.

4. Pilot ops docs
- Create `docs/pilot_terms.md` (evaluation-only terms).
- Create `docs/pilot_runbook.md` (submission flow + failure handling templates).
- Create `demo_packet/` with a reusable packet pointer/readme for demo/smoke/API docs.

5. Cloud stress sanity + artifact verification
- Execute 10 back-to-back cloud runs (alternating known packets).
- Persist run metadata and downloaded artifacts under `reference/pass_052/cloud_runs/`.
- Generate `summary.json` and `artifact_contract_report.json` validating:
  - `evidence_graph.json`
  - `chronology.pdf`
  - `missing_records.csv`

6. Final pass report
- Summarize strict/pilot code changes, tests, cloud run outcomes, and any documented failures.
- Flag unresolved items from monitoring/rollback checks as follow-ups if infra access limits full validation.

## Acceptance Criteria
- Pilot mode can return `REVIEW_RECOMMENDED` for LUQA meta-language ban (not `BLOCKED`).
- Strict mode behavior unchanged for LUQA meta-language ban.
- Focused tests pass.
- Pass folder contains 10-run cloud evidence + artifact contract report.
- Required pilot docs exist.
