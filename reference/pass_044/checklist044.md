# Pass 044 Checklist — Multi-Firm Parallel Upload Simulation + Drift Baseline Repair

## PASSCHECKLIST.md Responses

### 1. System State
- **Stage:** Hardening → Early Productization
- **Features allowed:** No
- **Reason:** We are in pilot-prep. Operational correctness under real load is higher priority than new features.

### 2. Failure Class Targeted
- **Primary:** ☑ Operational failure under concurrent intake
- **Secondary:** ☑ Trust erosion risk (drift SKIP masquerading as PASS)
- **Why now:** Parallel intake is the first real stress test of the Pass 043 queue. A double-claim bug in production could produce a PDF containing another patient's records — unrecoverable for a PI firm.

### 3. Failure Defined
- Drift SKIP in all 6 regression cases despite Pass 043 baselines existing.
- Parallel upload behavior untested — queue correctness unproven under concurrency.
- Both are systemic, reproducible, and not packet-specific.

### 4. Binary Success State
- Drift reports RUN for all cases with Pass 043 baselines.
- Simulator: 0 bad states across 5×3 run.
- CI test passes in ≤ 120s.

### 5. Architectural Move
- Standardized baseline layout (per-case subdirs).
- Baseline auto-resolution in drift checker.
- Per-run isolated temp dirs.
- Simulator as reusable hardening script.

### 6. Invariants Introduced
- INV-P1: drift never silently SKIP when baseline exists.
- INV-P2: simulator exits non-zero on any bad state.
- INV-P3: per-run temp dirs are isolated.

### 7. Tests Added
- Unit: baseline exists → drift must be RUN.
- Integration CI: `test_parallel_uploads.py` (2×2, concurrency=2, crash in 5s, 120s limit).
- Simulator: large 5×3 run with bad-state detectors.

### 8. Risk Reduced
- Trust risk (silent drift SKIP).
- Variability / artifact cross-contamination under parallelism.
- Legal risk (wrong patient's records in output).

### 9. Overfitting Check
- General: no dependency on specific packet or batch.
- Per-run temp dirs applies to all deployments.
- Baseline layout standard applies to all future passes.

### 10. Cancellation Test
- Wrong patient data in output → eliminated by INV-P3.
- Silent regression failures → eliminated by INV-P1.
- Unknown crash causes → improved by bad-state detector.

---

## Implementation Checklist

### A) Drift Baseline Repair

- [ ] **Update `run_regression.py`** to write baselines in standard layout:
  - `reference/pass_044/output/<case_id>/run_metadata.json`
  - `reference/pass_044/output/<case_id>/case_signals.json`
  - `reference/pass_044/output/<case_id>/leverage_output.json`
  - `reference/pass_044/output/<case_id>/trajectory_output.json`
  - `reference/pass_044/output/<case_id>/invariant_results.json` (optional)
  - `reference/pass_044/output/<case_id>/output_INTERNAL.pdf` (optional)
  - `reference/pass_044/output/<case_id>/output_MEDIATION.pdf` (optional)
- [ ] **Also back-fill Pass 043 baselines** by copying/re-exporting existing flat files into `reference/pass_043/output/<case_id>/` layout
- [ ] **Update drift checker** (`run_regression.py` or `verify_invariant_harness.py`):
  - Auto-resolve baseline dir: default to previous pass `reference/pass_04N/output/<case_id>/`
  - If baseline exists → status `RUN`
  - If baseline missing → status `SKIP` (with reason + counter in report)
- [ ] **Unit test**: when baseline file exists, drift must return `RUN` (not `SKIP`)
- [ ] **Acceptance gate**: Pass 044 regression shows drift `RUN` for all cases with Pass 043 baselines

### B) Parallel Upload Simulator

- [ ] **Create `scripts/simulate_parallel_uploads.py`** with:
  - Args: `--firms`, `--per-firm`, `--concurrency`, `--duplicate-rate`, `--cancel-rate`, `--crash-after-seconds`, `--max-runtime-seconds`, `--packets-dir`, `--out`
  - Enqueue jobs in bursts (simulate multi-firm uploads)
  - Re-submit duplicate enqueue requests at configured rate
  - Cancel some jobs (queued + best-effort running) at configured rate
  - Optionally kill a worker mid-run and restart
  - Wait for terminal states before reporting
  - Emit `simulator_report.json`

### C) Bad-State Detectors (Hard Fails in Simulator)

- [ ] **Double-claim detector**: poll `runs` table, flag if same `run_id` has overlapping lease claim windows across two different `worker_id`s
- [ ] **Success-without-artifacts detector**: after any run reaches `succeeded`, query `artifacts` and verify all `REQUIRED_ARTIFACT_TYPES` are present with `write_state='committed'`
- [ ] **Duplicate committed artifact detector**: flag if same `(run_id, artifact_type)` has two committed rows with different hashes
- [ ] **Idempotency violation detector**: re-enqueue same packet, verify returned `run_id` matches existing run
- [ ] **Ghost-running detector**: flag any run with `status='running'` and `lock_expires_at` past 2× heartbeat interval with no heartbeat update
- [ ] **Determinism check**: enqueue same packet (new idempotency key), wait for completion, compare artifact hashes to first run

### D) Minimal Hardening Fixes (only if simulator surface issues)

- [ ] **Per-run temp dirs**: `pipeline.py` — use `/tmp/linecite/<run_id>/` for all intermediate files
- [ ] **Artifact filenames include run_id**: ensure no cross-run collisions possible (update `artifacts_writer.py`)
- [ ] **Heartbeat jitter**: add small random sleep offset in `runner.py` / `queue.py` heartbeat to avoid thundering herd
- [ ] **Cooperative cancel checks**: check canceled status between major pipeline stages in `pipeline.py`
- [ ] **Verify `REQUIRED_ARTIFACT_TYPES` is centralized**: confirm it lives only in `queue.py`, not duplicated elsewhere

### E) CI Integration Test

- [ ] **Create `tests/integration/test_parallel_uploads.py`**:
  - Params: `--firms 2 --per-firm 2 --concurrency 2 --duplicate-rate 0.5 --cancel-rate 0.25 --crash-after-seconds 5 --max-runtime-seconds 120`
  - Must finish and produce `simulator_report.json` with `0 bad states`
- [ ] **Pilot packet fixtures**: ensure `tests/fixtures/pilot_packets/` exists with ≥1 small packet

### F) Governance

- [ ] **Add INV-P1, INV-P2, INV-P3** to `governance/invariants.md`
- [ ] **Write `reference/pass_044/release_notes.md`**

### G) Regression & Outputs

- [ ] **Run full regression** with `--out reference/pass_044/ --prev-out reference/pass_043/`
  - Must produce: `CASES PASS`, `STATIC PASS`, `DRIFT PASS` with RUN for all based cases
- [ ] **Run large simulator**: 5×3, concurrency=3, dup=0.2, cancel=0.1, crash enabled
  - Must produce: `simulator_report.json` with `0 bad states`
- [ ] **CI test passes** in ≤ 120s
- [ ] **Commit all outputs** to `reference/pass_044/`

---

## Acceptance Gates (Binary)

| Gate | Status |
|------|--------|
| Full regression PASS + DRIFT RUN | [ ] |
| Large simulator 0 bad states | [ ] |
| CI test passes ≤ 120s | [ ] |
| `simulator_report.json` in pass_044 | [ ] |
| Release notes written | [ ] |
