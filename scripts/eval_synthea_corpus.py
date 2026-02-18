from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_sample_172 import extract_pdf_text, run_sample_pipeline, score_report


def _page_count(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    return doc.page_count


def evaluate_case(pdf_path: Path, eval_dir: Path) -> dict:
    run_id = f"eval-corpus-{uuid4().hex[:8]}"
    out_pdf_path, ctx = run_sample_pipeline(pdf_path, run_id)
    case_dir = eval_dir / pdf_path.stem
    case_dir.mkdir(parents=True, exist_ok=True)
    output_pdf = case_dir / "output.pdf"
    shutil.copyfile(out_pdf_path, output_pdf)
    report_text = extract_pdf_text(output_pdf)
    score = score_report(report_text, ctx)

    entries = ctx.get("projection_entries", [])
    entry_count = len(entries)
    citation_nonempty = sum(1 for e in entries if (getattr(e, "citation_display", "") or "").strip())
    citation_ratio = round((citation_nonempty / entry_count), 3) if entry_count else 0.0
    unknown_provider_count = sum(1 for e in entries if (getattr(e, "provider_display", "") or "").strip().lower() == "unknown")
    unknown_provider_ratio = round((unknown_provider_count / entry_count), 3) if entry_count else 0.0
    pages = _page_count(pdf_path)

    min_density_ok = True
    if pages >= 80:
        min_density_ok = entry_count >= 4
    elif pages >= 20:
        min_density_ok = entry_count >= 3
    elif pages >= 8:
        min_density_ok = entry_count >= 2
    else:
        min_density_ok = entry_count >= 1

    case_pass = bool(
        score["overall_pass"]
        and min_density_ok
        and citation_ratio >= 0.9
        and entry_count > 0
    )
    return {
        "source_pdf": str(pdf_path),
        "pages": pages,
        "entry_count": entry_count,
        "citation_ratio": citation_ratio,
        "unknown_provider_ratio": unknown_provider_ratio,
        "base_overall_pass": score["overall_pass"],
        "min_density_ok": min_density_ok,
        "case_pass": case_pass,
        "scorecard": score,
    }


def evaluate_corpus(packets_dir: Path, max_cases: int, seed: int) -> dict:
    eval_dir = ROOT / "data" / "evals" / "synthea_corpus"
    eval_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted([p for p in packets_dir.glob("*.pdf") if p.is_file()])
    if not pdfs:
        raise FileNotFoundError(f"No PDFs found at {packets_dir}")
    rng = random.Random(seed)
    if max_cases > 0 and len(pdfs) > max_cases:
        idx = sorted(rng.sample(range(len(pdfs)), max_cases))
        selected = [pdfs[i] for i in idx]
    else:
        selected = pdfs

    rows: list[dict] = []
    for pdf in selected:
        rows.append(evaluate_case(pdf, eval_dir))

    total = len(rows)
    passed = sum(1 for r in rows if r["case_pass"])
    pass_rate = round((passed / total), 3) if total else 0.0
    low_density = [r["source_pdf"] for r in rows if not r["min_density_ok"]]
    low_citation = [r["source_pdf"] for r in rows if r["citation_ratio"] < 0.9]
    failing = [r["source_pdf"] for r in rows if not r["case_pass"]]

    summary = {
        "packets_dir": str(packets_dir),
        "evaluated_cases": total,
        "passed_cases": passed,
        "pass_rate": pass_rate,
        "target_pass_rate": 0.95,
        "overall_pass": pass_rate >= 0.95,
        "low_density_cases": low_density[:20],
        "low_citation_cases": low_citation[:20],
        "failing_cases": failing[:20],
        "results": rows,
    }
    (eval_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate litigation chronology quality on Synthea packet corpus.")
    parser.add_argument("--packets-dir", default=str(ROOT / "data" / "synthea" / "packets"))
    parser.add_argument("--max-cases", type=int, default=30, help="0 means all cases.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    summary = evaluate_corpus(Path(args.packets_dir), args.max_cases, args.seed)
    print(json.dumps({k: summary[k] for k in ("evaluated_cases", "passed_cases", "pass_rate", "overall_pass")}, indent=2))
    return 0 if summary["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
