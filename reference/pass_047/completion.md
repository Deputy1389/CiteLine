# Pass 047 Completion Note

Date: 2026-03-04

## Scope Completed

Implemented and validated Phase 1 API facade lifecycle endpoints under `/v1/jobs`:

- `POST /v1/jobs`
- `GET /v1/jobs/{job_id}`
- `GET /v1/jobs/{job_id}/artifacts`
- `GET /v1/jobs/{job_id}/artifacts/{filename}`
- `POST /v1/jobs/{job_id}/cancel`

Feature flag gating (`API_V1_JOBS_ENABLED`) is enforced at route entry.

## Code Changes

- Added artifact download endpoint to facade:
  - `apps/api/routes/jobs_v1.py`
- Added integration coverage for status normalization and download:
  - `tests/integration/test_api_v1_jobs.py`

## Validation Evidence

### Pass-047 targeted test file

Command:

`python -m pytest -q tests/integration/test_api_v1_jobs.py`

Result:

- 4 passed

### Broader API integration subset

Command:

`python -m pytest -q tests/integration/test_api_cancel_run.py tests/integration/test_api_delete_matter.py tests/integration/test_api_e2e.py tests/integration/test_api_hardening.py tests/integration/test_api_lists.py tests/integration/test_api_route_prefixes.py tests/integration/test_api_v1_jobs.py`

Result:

- 6 passed
- 7 failed

Failures observed outside pass-047 facade scope:

- `tests/integration/test_api_cancel_run.py::test_cancel_run` (expects `run['id']` but run creation currently returns 422 in that path)
- `tests/integration/test_api_delete_matter.py::test_delete_matter_blocked_with_active_run` (expects active-run delete block; got `204`)
- `tests/integration/test_api_e2e.py::TestApiE2E::test_happy_path` (run start expected `202`, got `422`)
- `tests/integration/test_api_hardening.py::test_path_traversal` (expects `404`, got `422` due to `export_mode` requirement for PDF download path)
- `tests/integration/test_api_lists.py::TestApiLists::test_list_endpoints` (expects two runs listed; got zero due to run creation mismatch)
- `tests/integration/test_api_route_prefixes.py::*` (DB setup issue in those tests: `no such table: firms`)

## Notes

- Pass-047 acceptance criteria for `/v1/jobs` lifecycle and facade tests are satisfied locally.
- Broader API failures indicate existing integration test drift and setup inconsistencies unrelated to the new `/v1/jobs` endpoint logic.
