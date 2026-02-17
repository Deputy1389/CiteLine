from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import fitz  # pymupdf


_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_TIMEFRAME_RE = re.compile(
    r"timeframe\s+from\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)

_REQUIRED_CHECKS = [
    ("04/29/2013", ["gunshot"]),
    ("05/07/2013", ["orif", "rotator", "bullet"]),
    ("05/21/2013", ["debrid", "infect"]),
    ("10/10/2013", ["hardware", "rotator", "debrid"]),
    ("01/21/2014", ["follow"]),
]


@dataclass(frozen=True)
class GoldChronology:
    text: str
    timeframe_start: str | None
    timeframe_end: str | None
    unique_dates: list[str]


def _extract_gold_text(pdf_path: Path) -> GoldChronology:
    doc = fitz.open(str(pdf_path))
    pages = [doc[i].get_text("text") or "" for i in range(doc.page_count)]
    trigger_idx = []
    for idx, text in enumerate(pages):
        if (
            "Brief Summary/Flow of Events" in text
            or "Detailed Chronology" in text
            or "Medical records provided for review span a timeframe" in text
        ):
            trigger_idx.append(idx)
    if not trigger_idx:
        combined = "\n".join(pages)
    else:
        start = min(trigger_idx)
        end = min(len(pages), start + 36)
        combined = "\n".join(pages[start:end])

    timeframe_start = None
    timeframe_end = None
    m = _TIMEFRAME_RE.search(combined)
    if m:
        timeframe_start = m.group(1)
        timeframe_end = m.group(2)

    unique_dates = sorted(set(_DATE_RE.findall(combined)), key=lambda d: datetime.strptime(d, "%m/%d/%Y"))
    return GoldChronology(
        text=combined,
        timeframe_start=timeframe_start,
        timeframe_end=timeframe_end,
        unique_dates=unique_dates,
    )


def _parse_md_entries(paralegal_md: str) -> tuple[dict[str, list[str]], list[str]]:
    by_date: dict[str, list[str]] = {}
    ordered_dates: list[str] = []
    current_date: str | None = None
    for line in paralegal_md.splitlines():
        m = re.match(r"^##\s+(\d{2}/\d{2}/\d{4})\s*$", line.strip())
        if m:
            current_date = m.group(1)
            if current_date not in by_date:
                by_date[current_date] = []
                ordered_dates.append(current_date)
            continue
        if current_date and line.strip().startswith("- "):
            by_date[current_date].append(line.strip()[2:].strip())
    return by_date, ordered_dates


def evaluate_paralegal_chronology(paralegal_md: str, sample_pdf_path: Path) -> dict:
    gold = _extract_gold_text(sample_pdf_path)
    by_date, ordered_dates = _parse_md_entries(paralegal_md)

    generated_event_count = sum(len(v) for v in by_date.values())
    density_threshold = max(12, min(40, int(len(gold.unique_dates) * 0.60)))

    required_results: dict[str, bool] = {}
    for date_str, tokens in _REQUIRED_CHECKS:
        combined = " ".join(by_date.get(date_str, [])).lower()
        required_results[date_str] = bool(combined) and all(token in combined for token in tokens)

    coverage_ok = True
    if gold.timeframe_start and gold.timeframe_start not in by_date:
        coverage_ok = False
    if gold.timeframe_end and gold.timeframe_end not in by_date:
        coverage_ok = False

    last_follow_up_ok = "01/21/2014" in by_date
    density_ok = generated_event_count >= density_threshold

    checks = {
        "required_dates_and_milestones": all(required_results.values()),
        "coverage_includes_gold_timeframe": coverage_ok,
        "includes_last_follow_up_01_21_2014": last_follow_up_ok,
        "density_threshold_met": density_ok,
    }
    passed = all(checks.values())
    score = int(round((sum(1 for ok in checks.values() if ok) / len(checks)) * 100))

    return {
        "passed": passed,
        "score": score,
        "gold_timeframe_start": gold.timeframe_start,
        "gold_timeframe_end": gold.timeframe_end,
        "gold_unique_date_count": len(gold.unique_dates),
        "generated_date_count": len(ordered_dates),
        "generated_event_count": generated_event_count,
        "density_threshold": density_threshold,
        "required_event_checks": required_results,
        "checks": checks,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate ParalegalChronology.md against sample packet gold chronology.")
    parser.add_argument("--sample-pdf", required=True, help="Path to sample-medical-chronology172.pdf")
    parser.add_argument("--paralegal-md", required=True, help="Path to generated ParalegalChronology.md")
    parser.add_argument("--json-out", default="", help="Optional path to write JSON report")
    args = parser.parse_args()

    sample_pdf = Path(args.sample_pdf)
    md_path = Path(args.paralegal_md)
    if not sample_pdf.exists():
        raise SystemExit(f"sample pdf not found: {sample_pdf}")
    if not md_path.exists():
        raise SystemExit(f"paralegal chronology markdown not found: {md_path}")

    report = evaluate_paralegal_chronology(md_path.read_text(encoding="utf-8"), sample_pdf)
    print("Paralegal Chronology Evaluation")
    print(f"Score: {report['score']}/100")
    print(f"Passed: {report['passed']}")
    print(
        "Gold timeframe: "
        f"{report['gold_timeframe_start']} -> {report['gold_timeframe_end']}"
    )
    print(
        "Generated density: "
        f"{report['generated_event_count']} events across {report['generated_date_count']} dates "
        f"(threshold {report['density_threshold']})"
    )
    for date_str, ok in report["required_event_checks"].items():
        print(f"Required {date_str}: {'OK' if ok else 'MISSING'}")

    if args.json_out:
        json_path = Path(args.json_out)
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote report JSON: {json_path}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
