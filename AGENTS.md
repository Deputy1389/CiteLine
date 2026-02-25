# CiteLine: Agent Guidelines

This file captures repo-specific guidance for agents working in `C:\Citeline`.

## Cross-Repo Frontend Location (Production UI)

- The production `www.linecite.com/app` frontend (Command Center / review UI) is in `C:\eventis\website`.
- When debugging routes like `/app/cases/:id/review`, check `C:\eventis\website` first (not `C:\Citeline\apps/ui`).
- `C:\Citeline\apps/ui` is a separate frontend and may not match production behavior.

## Repo Boundaries (Read Before Patching)

- `C:\Citeline` owns worker pipeline, API routes, shared models, persistence, and artifact generation.
- `C:\eventis\website` owns the production web UI used on `www.linecite.com/app/*`.
- If a bug is visible on `linecite.com`, identify the failing layer first (worker vs API vs production frontend) before changing code.

## Deployment Map (Current Working Assumption)

- Render/API deploys from the web/backend repo and can change endpoint behavior without touching the worker host.
- Oracle worker runs separately and typically needs manual update + restart after worker code changes.
- After worker changes, verify the running worker commit before testing new uploads.

Common worker commands (Oracle):

```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165
cd /opt/citeline && git pull
sudo systemctl restart linecite-worker
sudo journalctl -u linecite-worker -f
```

## The 4 Systemic Patterns (Must Read)

These are the root causes of most issues. When something breaks, check these first:

### 1. Pipeline Fragmentation (Root Cause)

Problem: Multiple pipeline entry points with different quality gates.

| Entry Point | Quality Gates |
|-------------|---------------|
| `apps/worker/pipeline.py:run_pipeline()` | Production |
| `scripts/run_case.py:run_case()` | Eval |

Rule: Any fix must apply to both entry points, or production must intentionally own the canonical behavior.

### 2. Config Doesn't Flow

Problem: API defaults can drift from `RunConfig` defaults.

Rule: When adding config fields, ensure `CreateRunRequest` defaults and `RunConfig` defaults match, and confirm API passthrough persists the field.

### 3. SQLAlchemy JSON Type Mismatches

Problem: Writing strings vs dicts to JSON columns causes runtime/API failures.

```python
# WRONG - writes string
run_row.metrics_json = model.model_dump_json()

# RIGHT - writes dict
run_row.metrics_json = model.model_dump()
```

Rule: Use `.model_dump()` for JSON columns, not `.model_dump_json()`.

### 4. Text Quality Too Late

Problem: Quality checks run after extraction, so OCR/font garbage pollutes providers/events.

Rule: Quality filtering must happen before provider detection and event extraction if the goal is cleaner downstream outputs.

## Attorney Readiness (Practical Standard)

A run is lawyer-ready if it is:

1. Source-verifiable quickly (claims have citations)
2. Substantive (not boilerplate/noise)
3. Provider-credible (no junk/placeholder entities)

Quality gates should support this standard; they are not a substitute for extraction quality.

## Important Files

| File | Purpose |
|------|---------|
| `apps/worker/pipeline.py` | Production pipeline entry |
| `apps/worker/lib/quality_gates.py` | Production quality gates wrapper |
| `apps/api/routes/runs.py` | Run API defaults + response serialization |
| `apps/api/routes/exports.py` | Latest export selection for audit/review flows |
| `packages/shared/models/domain.py` | Domain models (`RunConfig`) |
| `packages/db/models.py` | ORM models (`Run`, `Artifact`, etc.) |
| `reference/diagnostic_prompt.md` | Troubleshooting guide |

## Artifact Contract (UI-Critical)

- `evidence_graph.json` is the primary audit/review data source.
- UI consumers commonly depend on `extensions` fields such as:
  - `claim_rows`
  - `causation_chains`
  - `case_collapse_candidates`
  - `contradiction_matrix`
  - `narrative_duality`
  - `citation_fidelity`
- If artifact shape changes, validate all three layers: worker output, API download route, and production frontend parsing.

## Status Compatibility Matrix (Do Not Forget)

When adding/changing run statuses (e.g. `needs_review`), update all of:

- DB/ORM model status handling
- API serializers / response models (`runs`, `run detail`)
- export selection endpoints (e.g. `/matters/{id}/exports/latest`)
- frontend run list/status badges
- frontend audit/review loaders (status gating for artifact fetches)

If one layer misses the new status, the symptom is often a blank UI with no obvious error.

## Migration Discipline

- ORM model changes must be paired with a migration plan (migration file/ID or migration-safe fallback).
- If deployment order is uncertain, make writes conditional so old schemas do not break production.
- Avoid adding non-null columns in code first without confirming DB rollout timing.

## New Feature Checklist

- [ ] Works in production pipeline (`apps/worker/pipeline.py`)
- [ ] Works in eval path (`scripts/run_case.py`) or divergence is explicit/intentional
- [ ] Config defaults match between API and `RunConfig`
- [ ] JSON columns use `.model_dump()` (not `.model_dump_json()`)
- [ ] Artifact schema/shape changes are reflected in API + UI consumers
- [ ] Run status handling is updated everywhere (`success`, `partial`, `failed`, `needs_review`)
- [ ] Cloud smoke test completed (worker + API + UI), not just local execution

## Common Issues & First Checks

| Issue | Check |
|-------|-------|
| 500s on runs endpoints | JSON column types + serializer assumptions |
| Config changes do nothing | API defaults + config passthrough into `Run.config` |
| Audit/review page blank | Artifact endpoint status + frontend status gating |
| Unknown/junk providers | Text quality filtering timing + provider normalization |
| Eval passes, prod fails | Pipeline fragmentation / interface drift |

## Cloud Validation Checklist (After Pipeline/API Changes)

- [ ] Start a fresh cloud run on a real matter
- [ ] Worker reaches terminal status (`success`, `partial`, or `needs_review`) without crashing
- [ ] `GET /api/citeline/matters/{matter_id}/runs` returns `200`
- [ ] `GET /api/citeline/matters/{matter_id}/exports/latest` returns `200` for exportable statuses
- [ ] `GET /api/citeline/runs/{run_id}/artifacts/by-name/evidence_graph.json` returns `200`
- [ ] Review/Audit UI renders non-empty case data (not just shell chrome)

## Golden Packets (Useful Regression Set)

- `PacketIntake\\batch_029_complex_prior` - complex prior-history packet (stress test for chronology usefulness/noise)
- `PacketIntake\\05_minor_quick` - small/fast packet (quick cloud smoke + gating sanity)

Use at least one quick packet and one complex packet when validating systemic changes.

## Known Active Risks (As of 2026-02-25)

- Production frontend (`C:\eventis\website`) may still have status-gating drift for `needs_review`
- Eval path (`scripts/run_case.py` / eval scripts) can drift from production extractor signatures
- Early page-quality gate may over-flag pages and needs calibration
- LLM quota failures (`429`) can degrade narrative quality while core extraction still succeeds

## Run Status Values

- `pending` - Not started
- `running` - In progress
- `success` - Completed, quality passed
- `partial` - Completed with schema/validation warnings
- `failed` - Error during processing
- `needs_review` - Completed but quality gates failed (manual review required)

Last updated: 2026-02-25
