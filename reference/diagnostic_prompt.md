# CiteLine Diagnostic Prompt

Use this when the system has problems. Run each section and report results.

---

## SECTION 1: Quick Health Check

```bash
# Check if pipeline imports work
python -c "from apps.worker.pipeline import run_pipeline; print('Pipeline OK')"

# Check if quality gates import
python -c "from apps.worker.lib.quality_gates import run_quality_gates; print('Quality gates OK')"

# Check API imports
python -c "from apps.api.routes.runs import CreateRunRequest, RunResponse; print('API OK')"
```

**Report:** Which commands pass/fail?

---

## SECTION 2: Config Flow Issues?

**Run this to check config defaults:**
```bash
python -c "
from apps.api.routes.runs import CreateRunRequest
from packages.shared.models import RunConfig
print('CreateRunRequest pt_mode:', CreateRunRequest.model_fields['pt_mode'].default)
print('CreateRunRequest event_confidence_min_export:', CreateRunRequest.model_fields['event_confidence_min_export'].default)
print('RunConfig pt_mode:', RunConfig.model_fields['pt_mode'].default)
print('RunConfig event_confidence_min_export:', RunConfig.model_fields['event_confidence_min_export'].default)
"
```

**Expected:** Both should match (per_visit, 30)

**If mismatch:** The API defaults don't match RunConfig - check `apps/api/routes/runs.py`

---

## SECTION 3: JSON Column Type Issues?

**Check if persistence works:**
```bash
python -c "
from apps.worker.pipeline_persistence import persist_pipeline_state
print('Persistence imports OK')
"
```

**Check if config read handles both types:**
```python
# In pipeline.py, check line ~143:
# Should have: isinstance(run_row.config_json, dict) check
```

**If 500 errors:** Check `apps/worker/pipeline_persistence.py` - are you using `model_dump()` (dict) not `model_dump_json()` (string)?

---

## SECTION 4: Quality Gates Not Running?

**Check if gates are integrated in pipeline:**
```bash
# Search for quality gates in pipeline
grep -n "quality_gates\|run_quality_gates" apps/worker/pipeline.py
```

**Expected output:** Should see imports and function calls after rendering

**If missing:** Quality gates not in production pipeline - add call to `run_quality_gates()` after rendering

---

## SECTION 5: Text Quality Still Propagating?

**Check if early quality gate exists:**
```bash
grep -n "_assess_page_quality\|page_quality" apps/worker/pipeline.py
```

**Expected:** Should see `_assess_page_quality()` called BEFORE `detect_providers()`

**If missing:** Quality check runs too late - move before provider detection

---

## SECTION 6: Run Status Issues?

**Check if needs_review status exists:**
```bash
grep -n "needs_review" packages/db/models.py
```

**Check RunResponse has quality fields:**
```bash
grep -n "quality_gate" apps/api/routes/runs.py
```

---

## SECTION 7: Eval vs Production Different?

**Compare entry points:**

| File | Has Quality Gates? |
|------|-------------------|
| `apps/worker/pipeline.py` | ? |
| `scripts/run_case.py` | ? |
| `scripts/eval_sample_172.py` | ? |

**If different:** The pipeline fragmentation issue - fix by adding gates to all entry points

---

## SECTION 8: Test a Full Run

```bash
# Create test input
echo "%PDF-1.4" > /tmp/test.pdf

# Run pipeline (if you have test setup)
python -c "
from apps.worker.pipeline import run_pipeline
run_pipeline('test-run-id')
"

# Check status after run
# Should be: success, partial, failed, OR needs_review
```

---

## SECTION 9: Check Logs for Quality Gate Results

```bash
# Look for quality gate log messages
grep -i "quality.*gate\|attorney.*ready\|luqa" logs/*.log 2>/dev/null || echo "No log files found"

# Or in console output during run
```

---

## DIAGNOSIS TEMPLATE

Copy and fill this out when reporting problems:

```
## Problem Description
[What broke?]

## Quick Health Check Results
- Pipeline import: PASS/FAIL
- Quality gates import: PASS/FAIL  
- API import: PASS/FAIL

## Config Flow
- pt_mode in API: [value]
- pt_mode in RunConfig: [value]
- Match?: YES/NO

## JSON Columns
- 500 error?: YES/NO
- When does it occur?: [list_runs/get_run/etc]

## Quality Gates
- In pipeline.py?: YES/NO
- Status when gates fail: [value]

## Text Quality
- Early gate present?: YES/NO
- Before providers?: YES/NO

## Logs
[Attach relevant log excerpts]
```

---

## COMMON FIXES REFERENCE

| Problem | Likely Location | Fix |
|---------|----------------|-----|
| Config not flowing | `apps/api/routes/runs.py` | Match defaults to RunConfig |
| 500 on completed runs | `pipeline_persistence.py` | Use model_dump() not model_dump_json() |
| Bad quality = exported | `pipeline.py` | Add quality gates after rendering |
| Unknown providers | `pipeline.py` | Add early quality gate before providers |
| Eval ≠ Production | Multiple files | Add gates to all entry points |
