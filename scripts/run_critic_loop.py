from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_critique_packet import build_critique_packet
from scripts.run_case import run_case


def generate_fix_report(failures: list[dict[str, str]]) -> dict[str, Any]:
    if not failures:
        return {
            "action": "none",
            "summary": "No deterministic failures found; no patch recommended.",
            "targets": [],
        }

    targets: list[str] = []
    remediations: list[dict[str, str]] = []
    for f in failures:
        code = f.get("code")
        if code in {"atom_dump_leak", "provider_line_leak", "undated_pt_visit_leak"}:
            targets.append("apps/worker/steps/step12_export.py")
        if code in {"placeholder_dates"}:
            targets.append("apps/worker/steps/events/report_quality.py")
        if code in {"provider_misassignment"}:
            targets.append("apps/worker/project/chronology.py")
        if code in {"patient_scope_violation"}:
            targets.append("apps/worker/steps/step03b_patient_partitions.py")
        if code in {"empty_surgery_entry"}:
            targets.append("apps/worker/steps/events/report_quality.py")
        remediations.append(
            {
                "failure_code": code or "unknown",
                "proposal": f.get("hint", "Investigate failure and apply deterministic fix."),
            }
        )
    unique_targets = sorted(set(targets))
    return {
        "action": "manual_patch_required",
        "summary": f"{len(failures)} failure(s) detected; apply surgical patch and re-run.",
        "targets": unique_targets,
        "remediations": remediations,
    }


def run_loop(input_pdf: Path, case_id: str, iterations: int) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("--iterations must be >= 1")
    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    base_dir = ROOT / "data" / "evals" / case_id
    loop_dir = base_dir / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    for idx in range(1, iterations + 1):
        iteration_id = f"iter_{idx:02d}"
        iter_dir = loop_dir / iteration_id
        if iter_dir.exists():
            shutil.rmtree(iter_dir)
        iter_dir.mkdir(parents=True, exist_ok=True)

        run_label = f"{case_id}-{iteration_id}-{uuid4().hex[:6]}"
        run_payload = run_case(input_pdf=input_pdf, case_id=case_id, run_label=run_label)

        # Snapshot current case outputs into this iteration folder.
        current_eval_dir = ROOT / "data" / "evals" / case_id
        for name in ("output.pdf", "scorecard.json", "context.json"):
            src = current_eval_dir / name
            if src.exists():
                shutil.copyfile(src, iter_dir / name)

        packet = build_critique_packet(case_id=case_id, source_pdf=input_pdf, eval_dir=iter_dir)
        fix_report = generate_fix_report(packet["failures"])
        (iter_dir / "fix_report.json").write_text(json.dumps(fix_report, indent=2), encoding="utf-8")

        entry = {
            "iteration": idx,
            "run_id": run_payload["run_id"],
            "overall_pass": bool(packet["overall_pass"]),
            "failure_count": len(packet["failures"]),
            "scorecard_path": str(iter_dir / "scorecard.json"),
            "critique_packet_path": str(iter_dir / "critique_packet.md"),
            "fix_report_path": str(iter_dir / "fix_report.json"),
        }
        history.append(entry)

    summary = {
        "case_id": case_id,
        "input_pdf": str(input_pdf),
        "iterations": iterations,
        "all_passed": all(item["overall_pass"] for item in history),
        "history": history,
    }
    (loop_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic critique loop for N iterations.")
    parser.add_argument("--input", required=True, help="Path to source PDF.")
    parser.add_argument("--case-id", required=True, help="Case id under data/evals.")
    parser.add_argument("--iterations", type=int, default=5, help="Number of loop iterations.")
    args = parser.parse_args()

    summary = run_loop(input_pdf=Path(args.input), case_id=args.case_id, iterations=args.iterations)
    print(json.dumps(summary, indent=2))
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
