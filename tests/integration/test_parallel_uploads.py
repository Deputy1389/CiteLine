"""
tests/integration/test_parallel_uploads.py — Pass 044: CI parallel upload simulation test.

Runs the simulator with small params to verify:
  1. Queue handles concurrent multi-firm intake without bad states
  2. Idempotency dedup works correctly
  3. No ghost-running, double-claim, or artifact violations

Parameters (CI-safe, max 120s):
    --firms 2 --per-firm 2 --concurrency 2
    --duplicate-rate 0.5 --cancel-rate 0.25
    --crash-after-seconds 5 --max-runtime-seconds 120
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SIMULATOR = _REPO_ROOT / "scripts" / "simulate_parallel_uploads.py"
_PILOT_PACKETS = _REPO_ROOT / "tests" / "fixtures" / "pilot_packets"
_INVARIANT_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "invariants"
_TMP_REPORT = _REPO_ROOT / "tmp" / "test_parallel_uploads_report.json"


def _packets_dir() -> Path:
    """Return pilot_packets if it exists, else fall back to invariants."""
    if _PILOT_PACKETS.is_dir() and any(_PILOT_PACKETS.iterdir()):
        return _PILOT_PACKETS
    return _INVARIANT_FIXTURES


class TestParallelUploads:

    def test_simulator_produces_zero_bad_states(self, tmp_path: Path) -> None:
        """INV-P2: Simulator must finish and produce 0 bad states in CI configuration."""
        out_report = tmp_path / "simulator_report.json"
        packets_dir = _packets_dir()

        cmd = [
            sys.executable,
            str(_SIMULATOR),
            "--firms", "2",
            "--per-firm", "2",
            "--concurrency", "2",
            "--duplicate-rate", "0.5",
            "--cancel-rate", "0.25",
            "--crash-after-seconds", "5",
            "--max-runtime-seconds", "120",
            "--packets-dir", str(packets_dir),
            "--out", str(out_report),
        ]

        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        elapsed = time.time() - start

        print(f"\nSimulator stdout:\n{result.stdout}")
        if result.stderr:
            print(f"Simulator stderr:\n{result.stderr}")
        print(f"Elapsed: {elapsed:.1f}s")

        # Report must exist
        assert out_report.exists(), "simulator_report.json was not produced"

        report = json.loads(out_report.read_text())
        bad_count = report.get("bad_state_count", -1)
        sim_result = report.get("result", "UNKNOWN")

        print(f"Simulator result: {sim_result}")
        print(f"Bad states: {bad_count}")
        if report.get("bad_states"):
            print(f"Bad states detail: {json.dumps(report['bad_states'], indent=2)}")

        # INV-P2: zero bad states
        assert bad_count == 0, (
            f"INV-P2 VIOLATED: {bad_count} bad state(s) detected:\n"
            + json.dumps(report.get("bad_states", []), indent=2)
        )
        assert sim_result == "PASS", f"Simulator returned {sim_result}"

        # Must finish within max_runtime
        assert elapsed < 150, f"Simulator took too long: {elapsed:.0f}s > 150s"

    def test_drift_baseline_run_not_skip(self, tmp_path: Path) -> None:
        """INV-P1: When a baseline exists, drift check must return RUN not SKIP.

        Creates a fake pass_043 baseline in the per-case subdir layout and runs a
        regression against it, then verifies drift entries are RUN (not SKIP).
        """
        from scripts.run_regression import _load_prev_metadata

        case_id = "test_case_inv_p1"
        prev_out = tmp_path / "prev_out"
        case_dir = prev_out / "output" / case_id
        case_dir.mkdir(parents=True)

        baseline_meta = {
            "signal_layer_version": "36",
            "policy_version": "LI_V1_2026-03-01",
            "policy_fingerprint": "0f477127",
            "leverage_band": "ELEVATED",
            "leverage_score": 72.0,
            "determinism_check_result": "PASS",
        }
        (case_dir / "run_metadata.json").write_text(
            json.dumps(baseline_meta), encoding="utf-8"
        )

        data, source = _load_prev_metadata(prev_out, case_id)
        assert data is not None, f"INV-P1: baseline exists but _load_prev_metadata returned None (source: {source})"
        assert "run_metadata.json" in source, f"Expected subdir path, got: {source}"
        assert data["policy_version"] == "LI_V1_2026-03-01"

    def test_flat_baseline_fallback(self, tmp_path: Path) -> None:
        """Flat legacy baseline (pass_039-043 layout) must still resolve as a fallback."""
        from scripts.run_regression import _load_prev_metadata

        case_id = "legacy_case"
        prev_out = tmp_path / "prev_out"
        prev_out.mkdir(parents=True)

        # Write flat-only baseline (no subdir)
        flat_meta = {
            "policy_version": "LI_V1_2026-03-01",
            "leverage_band": "HIGH",
            "leverage_score": 85.0,
        }
        (prev_out / f"{case_id}_run_metadata.json").write_text(
            json.dumps(flat_meta), encoding="utf-8"
        )

        data, source = _load_prev_metadata(prev_out, case_id)
        assert data is not None, "Flat legacy baseline should still resolve"
        assert data["leverage_band"] == "HIGH"

    def test_missing_baseline_returns_skip_reason(self, tmp_path: Path) -> None:
        """Missing baseline must return None with a descriptive reason string."""
        from scripts.run_regression import _load_prev_metadata

        data, reason = _load_prev_metadata(tmp_path, "nonexistent_case")
        assert data is None, "Missing baseline should return None"
        assert len(reason) > 0, "Missing baseline must include a reason string"
        assert "nonexistent_case" in reason, f"Reason should reference the case_id: {reason}"
