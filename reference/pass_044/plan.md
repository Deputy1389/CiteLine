# Pass 044 — Multi-Firm Parallel Upload Simulation + Drift Baseline Repair

## 1. System State

**Stage:** Hardening → Early Productization (pilot-prep, not feature-building).  
**Features allowed:** No. This pass is purely operational hardening.

---

## 2. Failure Class Targeted

**Primary:** Operational failure under concurrent intake  
→ Duplicate claims, crash recovery, partial artifacts, and ghost-running workers under parallel load are unproven.  

**Secondary:** Trust erosion from drift checks silently reporting SKIP when they should be running against real baselines.

---

## 3. Define the Failure Precisely

### Drift SKIP masquerading as PASS
- `run_regression.py` outputs drift comparisons that say `[PASS] case1: SKIP`.
- SKIP is not a comparison — it just means no baseline was found.
- The baseline *does* exist in `reference/pass_043/` but is in a flat layout rather than per-case subdirectories, so the drift checker can't find it.
- **Artifact:** `reference/pass_043/drift_report.json` — every case shows SKIP.
- **Systemic:** Yes — affects all future regressions unless fixed.

### Parallelism unproven
- The Pass 043 queue was unit and integration tested, but never run under concurrent multi-firm intake.
- Real failure modes (double-claim, ghost-running, idempotency collisions) are only detectable under load.
- **No script exists** to simulate multi-firm parallel uploads against the queue.

---

## 4. Binary Success State

After Pass 044:

- **Drift SKIP is eliminated** for all cases that have Pass 043 baselines — every case reports drift `RUN`.
- **Zero bad states** detected by simulator over a 5-firm × 3-packet run with concurrency=3, dup-rate=0.2, cancel-rate=0.1, crash enabled.
- **CI integration test** (`test_parallel_uploads.py`) passes in under 120s with 0 bad states.
- Full regression: `CASES PASS`, `STATIC PASS`, `DRIFT PASS` (RUN for cases with baselines).
- `reference/pass_044/simulator_report.json` exists and shows 0 bad-state events.

---

## 5. Architectural Move

- **Standardize baseline layout** from flat `reference/pass_043/case1_signals.json` → per-case subdirs `reference/pass_043/output/<case_id>/`.
- **Drift checker gets explicit baseline resolution**: auto-discovers previous-pass output dir, distinguishes SKIP (no baseline) from RUN.
- **Simulator as a first-class script**: `scripts/simulate_parallel_uploads.py` — not a one-off hack, built to be reusable for any pass.
- **Bad-state detectors as hard invariant checks**: double-claim, success-without-artifacts, idempotency violation, ghost lease.

---

## 6. Invariants Introduced

| ID | Invariant | Enforced In | Tested In |
|----|-----------|-------------|-----------|
| **INV-P1** | Drift checker must never silently SKIP a case that has a baseline. | `run_regression.py` + `verify_invariant_harness.py` | Unit test: baseline exists → RUN |
| **INV-P2** | Simulator must exit non-zero on any bad state. | `simulate_parallel_uploads.py` | CI test `test_parallel_uploads.py` |
| **INV-P3** | Per-run artifact directories must be isolated: `/tmp/linecite/<run_id>/` | `pipeline.py` + `artifacts_writer.py` | Simulator (artifact collision detection) |

---

## 7. Files

### New
| File | Purpose |
|------|---------|
| `scripts/simulate_parallel_uploads.py` | Multi-firm parallel upload simulator with bad-state detectors |
| `tests/integration/test_parallel_uploads.py` | CI version of the simulator (small params, 120s limit) |
| `tests/fixtures/pilot_packets/` | Lightweight test packets for simulator (can reuse fixture symlinks) |

### Modify
| File | Change |
|------|--------|
| `scripts/run_regression.py` | Write baselines in standard per-case layout: `output/<case_id>/` |
| `scripts/verify_invariant_harness.py` (or `run_regression.py` drift section) | Baseline auto-resolution, RUN vs SKIP reporting with counter totals |
| `apps/worker/pipeline.py` | Per-run temp dir: `/tmp/linecite/<run_id>/` |
| `apps/worker/lib/artifacts_writer.py` | Artifact uniqueness check (same run_id + artifact_type cannot commit twice with different hashes) |
| `apps/worker/lib/queue.py` | Heartbeat jitter (avoid thundering herd), cooperative cancel check |
| `governance/invariants.md` | Append INV-P1, INV-P2, INV-P3 |

---

## 8. Risk Reduced

- **Trust risk:** Drift checks that silently skip erode confidence in the regression suite.
- **Variability risk:** Parallel artifact writes to shared temp dirs can produce collisions (mixed artifacts from two concurrent runs).
- **Legal risk (indirect):** A double-claimed run could produce merged output from two patients — catastrophic for PI medical records.

---

## 9. Overfitting Check

- Drift baseline fix is fully general — new standard layout applies to all future passes.
- Simulator is parameterized — not batch-specific.
- Per-run temp dirs are the correct general fix, not a packet-specific patch.
- Heartbeat jitter applies to any multi-worker deployment.

---

## 10. Cancellation Test

A $1k/month PI firm would cancel if:
- The system produces a PDF for the wrong patient (artifact cross-contamination). ← **eliminated by INV-P3**
- The pipeline silently crashes and they never know why. ← **improved by bad-state detector + ghost lease detection**
- Regression says "PASS" when nothing was actually compared. ← **eliminated by INV-P1**

---

## Simulator Spec

```
scripts/simulate_parallel_uploads.py
  --firms 5
  --per-firm 3
  --concurrency 3
  --duplicate-rate 0.2
  --cancel-rate 0.1
  --crash-after-seconds 20   (optional)
  --max-runtime-seconds 900
  --packets-dir tests/fixtures/pilot_packets/
  --out reference/pass_044/simulator_report.json
```

### Bad States (Hard Fails)
1. **Double-claim**: same `run_id` claimed by two workers with overlapping lease windows
2. **Success-without-artifacts**: `status=succeeded` while any `REQUIRED_ARTIFACT_TYPES` missing/uncommitted
3. **Duplicate committed artifact**: same `(run_id, artifact_type)` committed twice with different hashes
4. **Idempotency violation**: same `idempotency_key` returns different `run_id` while prior is queued/running/succeeded
5. **Ghost running**: `status=running` with expired lease beyond grace window (2× heartbeat interval)
6. **Determinism failure**: same packet re-enqueued (separate idempotency key) produces different artifact hashes

---

## Acceptance Gates (Binary)

Pass 044 is **DONE** only when ALL of the following are true:

- [ ] Full regression: `CASES PASS`, `STATIC PASS`, `DRIFT PASS` with drift `RUN` (not SKIP) for all cases that have Pass 043 baselines
- [ ] Large simulator run (5×3, concurrency=3, dup=0.2, cancel=0.1, crash enabled) → `0 bad states`
- [ ] CI test (`test_parallel_uploads.py`) passes in ≤ 120s with `0 bad states`
- [ ] `reference/pass_044/simulator_report.json` exists
- [ ] Release notes document drift baseline fix + parallel upload proof
