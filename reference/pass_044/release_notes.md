# Pass 044 Release Notes — Multi-Firm Parallel Upload Simulation + Drift Baseline Repair

**Date:** 2026-03-03  
**Status:** Implemented — pending cloud deployment and full regression

---

## Summary

Pass 044 hardens CiteLine for real pilot intake by:
1. **Fixing drift baselines** so regression correctly reports `RUN` (not `SKIP`) when prior-pass outputs exist
2. **Proving the queue survives parallel load** via a simulator with hard bad-state detectors

---

## Changes

### A) Drift Baseline Repair

**Problem:** All 6 regression cases were reporting `[PASS] case1: SKIP` because the drift
checker only looked for flat files (`case1_run_metadata.json`) but Pass 043 wrote them in
flat layout only — no standard per-case subdir existed yet.

**Fix:**
- `scripts/run_regression.py`: Updated `_load_prev_metadata` to check both layouts
  (per-case subdir first, flat fallback). Status is now `RUN` when baseline found.
- `scripts/verify_invariant_harness.py`: Added `_write_attest_artifacts_subdir()` which
  writes `output/<case_id>/run_metadata.json` alongside the flat files.
- Drift counters (`run`, `skip`, `version_change`, `drift_detected`) now appear in
  `regression_report.json` and `drift_report.json`.

**Invariant introduced:** INV-P1 — drift must never silently SKIP when a baseline exists.

### B) Multi-Firm Parallel Upload Simulator

**New file:** `scripts/simulate_parallel_uploads.py`

Simulates real pilot intake: N firms × M packets, concurrency C, with duplicate and cancel rates.
Features:
- Bursted enqueue (concurrent)
- Automatic idempotency verification (re-enqueue → same run_id)
- Configurable cancel injection
- Optional worker crash simulation (logs event for production systemd restart)
- Continuous bad-state detector loop (5 detectors)
- Emits `simulator_report.json`

### C) CI Integration Test

**New file:** `tests/integration/test_parallel_uploads.py`

Contains:
- `test_simulator_produces_zero_bad_states` — runs simulator with CI-safe params (2×2, 120s)
- `test_drift_baseline_run_not_skip` — INV-P1 unit test (subdir baseline)
- `test_flat_baseline_fallback` — INV-P1 unit test (legacy flat baseline)
- `test_missing_baseline_returns_skip_reason` — SKIP must include a reason

### D) Minimal Hardening

- **Heartbeat jitter** (`runner.py`): Added ±20% random jitter to initial heartbeat wait to prevent thundering herd when multiple workers restart simultaneously.
- **INV-P3** added to `governance/invariants.md`.

---

## Invariants Added

| Invariant | Description |
|-----------|-------------|
| INV-P1 | Drift checker never silently SKIPs when baseline exists |
| INV-P2 | Simulator exits non-zero on any bad state |
| INV-P3 | Heartbeat jitter prevents thundering herd |

---

## Files Modified

| File | Change |
|------|--------|
| `scripts/run_regression.py` | Per-case subdir baseline, RUN/SKIP counters, docstring update |
| `scripts/verify_invariant_harness.py` | Added `_write_attest_artifacts_subdir()` |
| `apps/worker/runner.py` | Heartbeat jitter |
| `governance/invariants.md` | Added INV-P1, INV-P2, INV-P3 |

## Files Added

| File | Purpose |
|------|---------|
| `scripts/simulate_parallel_uploads.py` | Multi-firm parallel upload simulator |
| `tests/integration/test_parallel_uploads.py` | CI integration test + INV-P1 unit tests |

---

## Acceptance Gates

| Gate | Status |
|------|--------|
| Full regression CASES PASS | ⏳ pending |
| Full regression DRIFT RUN for all cases with baselines | ⏳ pending |
| Large simulator 5×3 → 0 bad states | ⏳ pending |
| CI test passes ≤ 120s | ⏳ pending |
| `simulator_report.json` in pass_044 | ⏳ pending |
