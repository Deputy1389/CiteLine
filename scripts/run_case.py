from __future__ import annotations

import argparse
import json
import shutil
import sys
import io
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
from apps.worker.lib.luqa import build_luqa_report
from apps.worker.lib.attorney_readiness import build_attorney_readiness_report
from apps.worker.lib.legal_usability import build_legal_usability_report
from apps.worker.lib.artifacts_writer import safe_copy, write_artifact_json, validate_artifacts_exist


def _write_fail_cover_pdf(out_pdf: Path, checklist: dict, luqa: dict | None = None, attorney: dict | None = None) -> None:
    luqa = luqa or {}
    attorney = attorney or {}
    if bool(checklist.get("pass")) and bool(luqa.get("luqa_pass", True)) and bool(attorney.get("attorney_ready_pass", True)):
        return
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader, PdfWriter

    fail_lines: list[str] = []
    if not bool(checklist.get("pass")):
        fail_lines.append("LITIGATION QA FAILED - Do Not Use Without Review")
        for gate_name, gate in (checklist.get("quality_gates") or {}).items():
            if not gate.get("pass", True):
                fail_lines.append(f"- {gate_name}")
                for detail in gate.get("details", [])[:2]:
                    fail_lines.append(f"  - {detail.get('code')}: {detail.get('message')}")
        for hard_name, hard in (checklist.get("hard_invariants") or {}).items():
            if not hard.get("pass", True):
                fail_lines.append(f"- {hard_name}")
                for detail in hard.get("details", [])[:2]:
                    fail_lines.append(f"  - {detail.get('code')}: {detail.get('message')}")
    if not bool(luqa.get("luqa_pass", True)):
        fail_lines.append("LITIGATION USABILITY FAIL")
        for failure in (luqa.get("failures") or [])[:5]:
            fail_lines.append(f"- {failure.get('code')}: {failure.get('message')}")
            for ex in (failure.get("examples") or [])[:2]:
                fail_lines.append(f"  - {str(ex)[:120]}")
    if not bool(attorney.get("attorney_ready_pass", True)):
        fail_lines.append("ATTORNEY READINESS FAIL")
        for failure in (attorney.get("failures") or [])[:5]:
            fail_lines.append(f"- {failure.get('code')}: {failure.get('message')}")
            for ex in (failure.get("examples") or [])[:2]:
                fail_lines.append(f"  - {str(ex)[:120]}")
    fail_lines.append("See: selection_debug.json, missing_records.json, luqa_report.json")

    cover_buf = io.BytesIO()
    c = canvas.Canvas(cover_buf, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, "CiteLine Validation Gate")
    c.setFont("Helvetica", 11)
    y = 720
    for line in fail_lines[:25]:
        c.drawString(50, y, line[:120])
        y -= 18
        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = 750
    c.save()
    cover_buf.seek(0)

    writer = PdfWriter()
    writer.append(PdfReader(cover_buf))
    writer.append(PdfReader(str(out_pdf)))
    with out_pdf.open("wb") as f:
        writer.write(f)


def run_case(input_pdf: Path, case_id: str, run_label: str | None = None) -> dict:
    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    run_id = run_label or f"eval-{case_id}-{uuid4().hex[:8]}"
    eval_dir = ROOT / "data" / "evals" / case_id
    eval_dir.mkdir(parents=True, exist_ok=True)

    rendered_pdf, ctx = run_sample_pipeline(input_pdf, run_id)
    out_pdf = eval_dir / "output.pdf"
    shutil.copyfile(rendered_pdf, out_pdf)
    artifact_dir = ROOT / "data" / "artifacts" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Build a deterministic artifact manifest and mirror core artifacts into eval_dir.
    manifest: dict[str, str | None] = dict(ctx.get("artifact_manifest") or {})
    for name in [
        "evidence_graph.json",
        "patient_partitions.json",
        "missing_records.json",
        "selection_debug.json",
        "claim_guard_report.json",
    ]:
        src = Path(manifest.get(name) or (artifact_dir / name))
        if src.exists():
            copied = safe_copy(src, eval_dir, name)
            manifest[name] = str(copied.resolve()) if copied else str(src.resolve())
        else:
            manifest[name] = None

    seed_semqa = {"run_id": run_id, "qa_pass": None, "quality_gates": {}, "metrics": {}}
    semqa_eval_path = write_artifact_json("semqa_debug.json", seed_semqa, eval_dir)
    write_artifact_json("semqa_debug.json", seed_semqa, artifact_dir)
    manifest["semqa_debug.json"] = str(semqa_eval_path.resolve())
    ctx["artifact_manifest"] = manifest

    report_text = extract_pdf_text(out_pdf)
    scorecard = score_report(report_text, ctx)
    checklist = build_litigation_checklist(
        run_id=run_id,
        source_pdf=str(input_pdf),
        report_text=report_text,
        ctx=ctx,
        chronology_pdf_path=out_pdf,
    )
    checklist_path = eval_dir / "qa_litigation_checklist.json"
    write_litigation_checklist(checklist_path, checklist)
    luqa = build_luqa_report(report_text, ctx)
    luqa_eval_path = write_artifact_json("luqa_report.json", luqa, eval_dir)
    write_artifact_json("luqa_report.json", luqa, artifact_dir)
    manifest["luqa_report.json"] = str(luqa_eval_path.resolve())
    attorney = build_attorney_readiness_report(report_text, ctx)
    attorney_eval_path = write_artifact_json("attorney_readiness_report.json", attorney, eval_dir)
    write_artifact_json("attorney_readiness_report.json", attorney, artifact_dir)
    manifest["attorney_readiness_report.json"] = str(attorney_eval_path.resolve())
    legal = build_legal_usability_report(report_text, ctx, luqa, attorney)
    legal_eval_path = write_artifact_json("legal_usability_report.json", legal, eval_dir)
    write_artifact_json("legal_usability_report.json", legal, artifact_dir)
    manifest["legal_usability_report.json"] = str(legal_eval_path.resolve())
    _write_fail_cover_pdf(out_pdf, checklist, luqa, attorney)
    semqa_debug = {
        "run_id": run_id,
        "hard_failures": checklist.get("hard_failures", []),
        "quality_gates": checklist.get("quality_gates", {}),
        "metrics": checklist.get("metrics", {}),
        "required_quality_gates": (checklist.get("failure_summary") or {}).get("required_quality_gates", []),
        "qa_pass": bool(checklist.get("pass")),
    }
    semqa_path = write_artifact_json("semqa_debug.json", semqa_debug, eval_dir)
    write_artifact_json("semqa_debug.json", semqa_debug, artifact_dir)
    manifest["semqa_debug.json"] = str(semqa_path.resolve())
    ctx["artifact_manifest"] = manifest

    # Validate manifest paths and keep context explicit.
    manifest_for_validation = {k: v for k, v in manifest.items()}
    artifacts_ok, missing_keys = validate_artifacts_exist(manifest_for_validation)

    scorecard["qa_pass"] = bool(checklist.get("pass"))
    scorecard["qa_score"] = int(checklist.get("score_0_100", 0) or 0)
    scorecard["luqa_pass"] = bool(luqa.get("luqa_pass"))
    scorecard["luqa_score"] = int(luqa.get("luqa_score_0_100", 0) or 0)
    scorecard["luqa_failures_count"] = len(luqa.get("failures") or [])
    scorecard["attorney_ready_pass"] = bool(attorney.get("attorney_ready_pass"))
    scorecard["attorney_ready_score"] = int(attorney.get("attorney_ready_score_0_100", 0) or 0)
    scorecard["attorney_ready_failures_count"] = len(attorney.get("failures") or [])
    scorecard["legal_pass"] = bool(legal.get("legal_pass"))
    scorecard["legal_score"] = int(legal.get("legal_score_0_100", 0) or 0)
    scorecard["legal_failures_count"] = len(legal.get("failures") or [])
    scorecard["model_score"] = scorecard.get("model_score", scorecard.get("surgery_count", 0))
    scorecard["score_0_100"] = int(checklist.get("score_0_100", scorecard.get("score_0_100", 0)) or 0)
    scorecard["overall_pass"] = bool(checklist.get("pass")) and bool(legal.get("legal_pass"))
    scorecard_path = eval_dir / "scorecard.json"
    scorecard_path.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")

    context_path = eval_dir / "context.json"
    context_payload = {
        "run_id": run_id,
        "input_pdf": str(input_pdf),
        "output_pdf": str(out_pdf),
        "qa_litigation_checklist": str(checklist_path),
        "qa_pass": bool(checklist.get("pass")),
        "luqa_pass": bool(luqa.get("luqa_pass")),
        "luqa_score": int(luqa.get("luqa_score_0_100", 0) or 0),
        "attorney_ready_pass": bool(attorney.get("attorney_ready_pass")),
        "attorney_ready_score": int(attorney.get("attorney_ready_score_0_100", 0) or 0),
        "legal_pass": bool(legal.get("legal_pass")),
        "legal_score": int(legal.get("legal_score_0_100", 0) or 0),
        "patient_manifest_ref": ctx.get("patient_manifest_ref"),
        "projection_entry_count": len(ctx.get("projection_entries", [])),
        "gaps_count": ctx.get("gaps_count", 0),
        "overall_pass": bool(checklist.get("pass")) and bool(legal.get("legal_pass")),
        "failure_summary": checklist.get("failure_summary", {}),
        "artifact_manifest": manifest,
        "artifact_manifest_ok": artifacts_ok,
        "artifact_manifest_missing": missing_keys,
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
