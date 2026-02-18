from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_sample_172 import extract_pdf_text, run_sample_pipeline, score_report
from scripts.litigation_qa import build_litigation_checklist, write_litigation_checklist


def _page_count(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    return doc.page_count


def _tier_from_path(pdf_path: Path) -> str:
    parent = pdf_path.parent.name.lower()
    if parent in {"mild", "moderate", "severe"}:
        return parent
    return "unknown"


def evaluate_case(pdf_path: Path, eval_dir: Path) -> dict:
    run_id = f"eval-chaos-{uuid4().hex[:8]}"
    out_pdf_path, ctx = run_sample_pipeline(pdf_path, run_id)
    case_dir = eval_dir / pdf_path.stem
    case_dir.mkdir(parents=True, exist_ok=True)
    output_pdf = case_dir / "output.pdf"
    shutil.copyfile(out_pdf_path, output_pdf)
    report_text = extract_pdf_text(output_pdf)

    score = score_report(report_text, ctx)
    checklist = build_litigation_checklist(
        run_id=run_id,
        source_pdf=str(pdf_path),
        report_text=report_text,
        ctx=ctx,
        chronology_pdf_path=output_pdf,
    )
    write_litigation_checklist(case_dir / "qa_litigation_checklist.json", checklist)

    entries = ctx.get("projection_entries", [])
    entry_count = len(entries)
    citation_nonempty = sum(1 for e in entries if (getattr(e, "citation_display", "") or "").strip())
    citation_ratio = round((citation_nonempty / entry_count), 3) if entry_count else 0.0
    pages = _page_count(pdf_path)
    min_density_ok = entry_count >= (2 if pages >= 8 else 1)

    case_pass = bool(score["overall_pass"] and checklist["pass"] and citation_ratio >= 0.9 and min_density_ok and entry_count > 0)
    return {
        "source_pdf": str(pdf_path),
        "tier": _tier_from_path(pdf_path),
        "pages": pages,
        "entry_count": entry_count,
        "citation_ratio": citation_ratio,
        "base_overall_pass": bool(score["overall_pass"]),
        "qa_pass": bool(checklist["pass"]),
        "min_density_ok": min_density_ok,
        "case_pass": case_pass,
        "scorecard": score,
        "qa": {
            "hard_failure_count": len(checklist.get("hard_failures", [])),
            "rubric_score_0_100": checklist.get("scores", {}).get("rubric_score_0_100"),
        },
    }


def evaluate_chaos_corpus(chaos_dir: Path) -> dict:
    eval_dir = ROOT / "data" / "evals" / "chaos_corpus"
    eval_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted([p for p in chaos_dir.rglob("*.pdf") if p.is_file()])
    if not pdfs:
        raise FileNotFoundError(f"No chaotic PDFs found at {chaos_dir}")

    rows: list[dict] = []
    for pdf in pdfs:
        rows.append(evaluate_case(pdf, eval_dir))

    total = len(rows)
    passed = sum(1 for r in rows if r["case_pass"])
    pass_rate = round((passed / total), 3) if total else 0.0

    by_tier: dict[str, dict] = {}
    for tier in ("mild", "moderate", "severe", "unknown"):
        subset = [r for r in rows if r["tier"] == tier]
        if not subset:
            continue
        tier_passed = sum(1 for r in subset if r["case_pass"])
        by_tier[tier] = {
            "cases": len(subset),
            "passed": tier_passed,
            "pass_rate": round(tier_passed / len(subset), 3),
            "avg_entries": round(sum(r["entry_count"] for r in subset) / len(subset), 2),
            "avg_rubric": round(
                sum((r.get("qa", {}).get("rubric_score_0_100") or 0) for r in subset) / len(subset),
                2,
            ),
        }

    summary = {
        "chaos_dir": str(chaos_dir),
        "evaluated_cases": total,
        "passed_cases": passed,
        "pass_rate": pass_rate,
        "target_pass_rate": 0.9,
        "overall_pass": pass_rate >= 0.9,
        "by_tier": by_tier,
        "failing_cases": [r["source_pdf"] for r in rows if not r["case_pass"]][:40],
        "results": rows,
    }
    (eval_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate litigation QA on chaotic Synthea packet corpus.")
    parser.add_argument("--chaos-dir", default=str(ROOT / "data" / "synthea" / "chaos"))
    args = parser.parse_args()

    summary = evaluate_chaos_corpus(Path(args.chaos_dir))
    print(
        json.dumps(
            {
                "evaluated_cases": summary["evaluated_cases"],
                "passed_cases": summary["passed_cases"],
                "pass_rate": summary["pass_rate"],
                "overall_pass": summary["overall_pass"],
                "by_tier": summary["by_tier"],
            },
            indent=2,
        )
    )
    return 0 if summary["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
