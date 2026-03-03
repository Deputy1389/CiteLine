"""
run_regression.py — Full Regression Orchestrator (Pass 39 / updated Pass 044)

Runs the complete invariant harness across all fixture cases and performs the
cross-run policy drift check required by govpreplan §6.

Usage:
    python scripts/run_regression.py \
        --fixtures tests/fixtures/invariants/ \
        --out reference/pass_044/ \
        [--prev-out reference/pass_043/]

Exit codes:
    0 — All invariants pass, all static checks pass, no unexpected drift
    1 — Any invariant failed, static check failed, or drift detected

Drift check (govpreplan §6, Pass 044 update):
    Baseline resolution order:
      1. <prev_out>/output/<case_id>/run_metadata.json  (per-case subdir layout)
      2. <prev_out>/<case_id>_run_metadata.json         (legacy flat layout)
    If --prev-out is provided and baseline exists → drift status is RUN.
    If baseline is missing → drift status is SKIP (with reason + counter in report).
    If --prev-out not provided: drift check is skipped entirely.
    INV-P1: drift must never silently SKIP when a baseline exists.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Import harness functions directly — no subprocess
from scripts.verify_invariant_harness import (
    run_case,
    check_D4_trajectory_signals_only,
    check_D5_renderer_display_only,
    _write_attest_artifacts,
    _write_attest_artifacts_subdir,
    _strip_private_keys,
    _utcnow_iso,
    _SIGNAL_LAYER_VERSION,
)


def _load_prev_metadata(prev_out_dir: Path, case_id: str) -> tuple["dict | None", str]:
    """Load run_metadata.json from a previous run, trying per-case subdir first then flat.

    Returns (data, source_path_str). If not found, returns (None, reason_str).
    INV-P1: callers must not silently treat None as PASS; they must mark SKIP with reason.
    """
    # 1. Per-case subdir layout (standard from Pass 044 onward)
    subdir_path = prev_out_dir / "output" / case_id / "run_metadata.json"
    if subdir_path.exists():
        try:
            with subdir_path.open("r", encoding="utf-8") as f:
                return json.load(f), str(subdir_path)
        except Exception:
            return None, f"parse error: {subdir_path}"

    # 2. Legacy flat layout (Pass 039–043)
    flat_path = prev_out_dir / f"{case_id}_run_metadata.json"
    if flat_path.exists():
        try:
            with flat_path.open("r", encoding="utf-8") as f:
                return json.load(f), str(flat_path)
        except Exception:
            return None, f"parse error: {flat_path}"

    return None, f"no baseline in {prev_out_dir}/output/{case_id}/ or {prev_out_dir}/{case_id}_run_metadata.json"


def run_drift_check(
    report: list[dict],
    prev_out_dir: Path,
) -> tuple[bool, list[dict], dict]:
    """Compare current run metadata against a previous run.

    Returns (passed: bool, drift_entries: list[dict], counters: dict).
    passed=True means: no unexpected drift (version changed or values identical).
    passed=False means: same version, values differ → POLICY_DRIFT_DETECTED.

    Per INV-P1: status is RUN when a baseline exists, SKIP (with reason) when missing.
    The counters dict tracks: run, skip, version_change, drift_detected.
    """
    drift_entries: list[dict] = []
    all_pass = True
    counters = {"run": 0, "skip": 0, "version_change": 0, "drift_detected": 0}

    for result in report:
        case_id = result["case"]

        # Get current policy version + band/score from _ext
        ext = result.get("_ext") or {}
        lev = ext.get("leverage_index_result") or {}
        lp = ext.get("leverage_policy") or {}
        curr_version = lp.get("version")
        curr_band = lev.get("band")
        curr_score = lev.get("score")

        prev_meta, meta_source = _load_prev_metadata(prev_out_dir, case_id)
        if prev_meta is None:
            # INV-P1: explicit SKIP with reason — never silent
            counters["skip"] += 1
            drift_entries.append({
                "case": case_id,
                "status": "SKIP",
                "reason": meta_source,
            })
            continue

        # Baseline found → RUN comparison
        counters["run"] += 1
        prev_version = prev_meta.get("policy_version")
        prev_band = prev_meta.get("leverage_band")
        prev_score = prev_meta.get("leverage_score")

        if curr_version != prev_version:
            # Intentional version change — record metrics, not a failure
            counters["version_change"] += 1
            band_changed = curr_band != prev_band
            score_changed = curr_score != prev_score
            drift_entries.append({
                "case": case_id,
                "status": "VERSION_CHANGE",
                "baseline_source": meta_source,
                "prev_version": prev_version,
                "curr_version": curr_version,
                "band_changed": band_changed,
                "prev_band": prev_band,
                "curr_band": curr_band,
                "score_changed": score_changed,
                "prev_score": prev_score,
                "curr_score": curr_score,
            })
            continue

        # Same version — values must be identical
        band_ok = curr_band == prev_band
        score_ok = (
            curr_score == prev_score
            or (curr_score is None and prev_score is None)
            or (
                curr_score is not None
                and prev_score is not None
                and abs(float(curr_score) - float(prev_score)) < 1e-9
            )
        )

        if band_ok and score_ok:
            drift_entries.append({
                "case": case_id,
                "status": "RUN",
                "baseline_source": meta_source,
                "version": curr_version,
                "band": curr_band,
                "score": curr_score,
            })
        else:
            all_pass = False
            counters["drift_detected"] += 1
            drift_entries.append({
                "case": case_id,
                "status": "POLICY_DRIFT_DETECTED",
                "baseline_source": meta_source,
                "version": curr_version,
                "prev_band": prev_band,
                "curr_band": curr_band,
                "prev_score": prev_score,
                "curr_score": curr_score,
            })

    return all_pass, drift_entries, counters


def main() -> int:
    parser = argparse.ArgumentParser(description="Citeline full regression orchestrator")
    parser.add_argument("--fixtures", required=True, help="Fixtures directory")
    parser.add_argument("--out", required=True, help="Output directory for this run's artifacts")
    parser.add_argument("--prev-out", default=None, dest="prev_out",
                        help="Previous run's output directory for drift check (optional)")
    args = parser.parse_args()

    fixtures_dir = Path(args.fixtures)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not fixtures_dir.is_dir():
        print(f"ERROR: fixtures directory not found: {fixtures_dir}", file=sys.stderr)
        return 1

    case_dirs = sorted(d for d in fixtures_dir.iterdir() if d.is_dir())
    if not case_dirs:
        print(f"ERROR: no case subdirectories found in {fixtures_dir}", file=sys.stderr)
        return 1

    print("=" * 60)
    print("CITELINE REGRESSION SUITE")
    print(f"Signal layer: v{_SIGNAL_LAYER_VERSION}")
    print(f"Fixtures: {fixtures_dir}")
    print(f"Output:   {out_dir}")
    if args.prev_out:
        print(f"Prev out: {args.prev_out}")
    print("=" * 60)

    # ── Static checks (run once) ─────────────────────────────────────────────
    print("\n[STATIC CHECKS]")
    d4 = check_D4_trajectory_signals_only()
    d5 = check_D5_renderer_display_only()
    static_pass = d4["passed"] and d5["passed"]

    for check in [d4, d5]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['invariant']}: {check['detail']}")

    # ── Per-case checks ──────────────────────────────────────────────────────
    print("\n[PER-CASE INVARIANTS]")
    report: list[dict] = []
    overall_case_pass = True

    for case_dir in case_dirs:
        result = run_case(case_dir)
        report.append(result)
        status = "PASS" if result["all_pass"] else "FAIL"
        if not result["all_pass"]:
            overall_case_pass = False
        print(f"\n  [{status}] {result['case']}")
        for inv in result.get("invariants", []):
            mark = "PASS" if inv["passed"] else "FAIL"
            print(f"       [{mark}] {inv['invariant']}: {inv['detail']}")

        # Write attest artifacts — flat (legacy) + per-case subdir (Pass 044 standard)
        _write_attest_artifacts(out_dir, result)
        _write_attest_artifacts_subdir(out_dir, result)

    # ── Drift check ──────────────────────────────────────────────────────────
    drift_pass = True
    drift_entries: list[dict] = []
    drift_counters: dict = {}

    if args.prev_out:
        prev_out_dir = Path(args.prev_out)
        print(f"\n[DRIFT CHECK] comparing against {prev_out_dir}")
        drift_pass, drift_entries, drift_counters = run_drift_check(report, prev_out_dir)
        for entry in drift_entries:
            mark = "PASS" if entry["status"] in ("RUN", "PASS", "VERSION_CHANGE") else ("WARN" if entry["status"] == "SKIP" else "FAIL")
            print(f"  [{mark}] {entry['case']}: {entry['status']}")
            if entry["status"] == "SKIP":
                print(f"         reason: {entry.get('reason', 'unknown')}")
            elif entry["status"] == "POLICY_DRIFT_DETECTED":
                print(f"         band: {entry['prev_band']} → {entry['curr_band']}")
                print(f"         score: {entry['prev_score']} → {entry['curr_score']}")
        print(f"  Drift report: run={drift_counters.get('run',0)} skip={drift_counters.get('skip',0)} version_change={drift_counters.get('version_change',0)} drift_detected={drift_counters.get('drift_detected',0)}")

        # Write drift report
        drift_report_path = out_dir / "drift_report.json"
        with drift_report_path.open("w", encoding="utf-8") as f:
            json.dump({
                "drift_pass": drift_pass,
                "prev_out": str(args.prev_out),
                "run_at": _utcnow_iso(),
                "counters": drift_counters,
                "entries": drift_entries,
            }, f, indent=2, default=str)
        print(f"  Drift report: {drift_report_path}")
    else:
        print("\n[DRIFT CHECK] skipped (no --prev-out provided)")

    # ── Summary ──────────────────────────────────────────────────────────────
    overall_pass = static_pass and overall_case_pass and drift_pass

    summary = {
        "overall_pass": overall_pass,
        "run_at": _utcnow_iso(),
        "signal_layer_version": _SIGNAL_LAYER_VERSION,
        "fixtures": str(fixtures_dir),
        "cases_total": len(report),
        "cases_pass": sum(1 for r in report if r["all_pass"]),
        "cases_fail": sum(1 for r in report if not r["all_pass"]),
        "static_checks": [d4, d5],
        "static_pass": static_pass,
        "drift_pass": drift_pass,
        "drift_counters": drift_counters,
        "drift_entries": drift_entries,
        "cases": _strip_private_keys(report),
    }

    report_path = out_dir / "regression_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n" + "=" * 60)
    print(f"CASES:  {summary['cases_pass']}/{summary['cases_total']} pass")
    print(f"STATIC: {'PASS' if static_pass else 'FAIL'}")
    print(f"DRIFT:  {'PASS' if drift_pass else 'FAIL (POLICY_DRIFT_DETECTED)'}")
    print(f"RESULT: {'ALL PASS' if overall_pass else 'FAILURES DETECTED'}")
    print(f"Report: {report_path}")
    print("=" * 60)

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
