from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_sample_172 import (
    ROOT,
    extract_pdf_text,
    run_sample_pipeline,
    score_report,
)
from scripts.litigation_qa import build_litigation_checklist, write_litigation_checklist


def run_case(input_pdf: Path, case_id: str, run_label: str | None = None) -> dict:
    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    run_id = run_label or f"eval-{case_id}-{uuid4().hex[:8]}"
    eval_dir = ROOT / "data" / "evals" / case_id
    eval_dir.mkdir(parents=True, exist_ok=True)

    rendered_pdf, ctx = run_sample_pipeline(input_pdf, run_id)
    out_pdf = eval_dir / "output.pdf"
    shutil.copyfile(rendered_pdf, out_pdf)

    report_text = extract_pdf_text(out_pdf)
    scorecard = score_report(report_text, ctx)
    scorecard_path = eval_dir / "scorecard.json"
    scorecard_path.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
    checklist = build_litigation_checklist(
        run_id=run_id,
        source_pdf=str(input_pdf),
        report_text=report_text,
        ctx=ctx,
        chronology_pdf_path=out_pdf,
    )
    checklist_path = eval_dir / "qa_litigation_checklist.json"
    write_litigation_checklist(checklist_path, checklist)

    context_path = eval_dir / "context.json"
    context_payload = {
        "run_id": run_id,
        "input_pdf": str(input_pdf),
        "output_pdf": str(out_pdf),
        "qa_litigation_checklist": str(checklist_path),
        "qa_pass": bool(checklist.get("pass")),
        "patient_manifest_ref": ctx.get("patient_manifest_ref"),
        "projection_entry_count": len(ctx.get("projection_entries", [])),
        "gaps_count": ctx.get("gaps_count", 0),
        "overall_pass": bool(scorecard.get("overall_pass")) and bool(checklist.get("pass")),
        "failure_summary": checklist.get("failure_summary", {}),
    }
    context_path.write_text(json.dumps(context_payload, indent=2), encoding="utf-8")
    return context_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one PDF through chronology pipeline and save report + scorecard.")
    parser.add_argument("--input", required=True, help="Path to source PDF.")
    parser.add_argument("--case-id", required=True, help="Eval case id, used under data/evals/<case-id>.")
    parser.add_argument("--run-label", help="Optional deterministic run label.")
    args = parser.parse_args()

    payload = run_case(Path(args.input), args.case_id, args.run_label)
    print(json.dumps(payload, indent=2))
    if payload.get("overall_pass"):
        return 0
    failure_summary = payload.get("failure_summary", {}) or {}
    if failure_summary.get("contract_failed"):
        return 4
    if failure_summary.get("hard_failed"):
        return 2
    if failure_summary.get("quality_failed"):
        return 3
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
