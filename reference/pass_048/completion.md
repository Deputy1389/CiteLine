# Pass 048 Completion Note

Date: 2026-03-04

## Scope Completed

Implemented idempotent create behavior for `POST /v1/jobs` using `Idempotency-Key`.

Behavior now:

- Same key + same payload => returns existing job (`202`) with same `job_id`
- Same key + different payload => `409`
- No key => default create behavior unchanged

## Code Changes

- `apps/api/routes/jobs_v1.py`
  - Added header handling for `Idempotency-Key`
  - Added key validation and hashing
  - Added replay lookup and conflict handling
  - Added insert-race fallback on unique-key collision
- `tests/integration/test_api_v1_jobs.py`
  - Added replay test
  - Added mismatch conflict test

## Validation Evidence

### Local integration tests

Command:

`python -m pytest -q tests/integration/test_api_v1_jobs.py`

Result:

- 6 passed

### Cloud deployment

- GitHub commit deployed: `072aee1` (`Pass 048: add idempotent POST /v1/jobs contract`)
- Render deploy: `dep-d6k8f77e9avs73f1ukqg`
- Status: `live`

### Cloud runtime smoke

Against `https://linecite-api.onrender.com`:

- Created firm/matter/document
- `POST /v1/jobs` with `Idempotency-Key` called twice
- Both responses returned same `job_id`
- Payload mismatch replay returned `409` with expected detail

