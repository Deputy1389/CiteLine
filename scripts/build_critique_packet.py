from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eval_sample_172 import extract_pdf_text


def failure_taxonomy(scorecard: dict[str, Any]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    if scorecard.get("forbidden_strings_found"):
        failures.append(
            {
                "code": "forbidden_strings",
                "severity": "critical",
                "hint": "Strengthen sanitize_for_report denylist and timeline text cleaner.",
            }
        )
    if scorecard.get("has_placeholder_dates"):
        failures.append(
            {
                "code": "placeholder_dates",
                "severity": "critical",
                "hint": "Enforce date sanity guard; render missing date as 'Date not documented'.",
            }
        )
    if scorecard.get("has_uuid_provider_ids"):
        failures.append(
            {
                "code": "uuid_provider_leak",
                "severity": "high",
                "hint": "Render provider display names only; never raw provider IDs.",
            }
        )
    if scorecard.get("has_raw_fragment_dump") or scorecard.get("has_atom_dump_marker"):
        failures.append(
            {
                "code": "atom_dump_leak",
                "severity": "critical",
                "hint": "Client PDF must render projection/events only; route debug trace to evidence artifact.",
            }
        )
    if scorecard.get("has_date_not_documented_pt_visit"):
        failures.append(
            {
                "code": "undated_pt_visit_leak",
                "severity": "high",
                "hint": "Exclude low-value undated encounters from client timeline.",
            }
        )
    if scorecard.get("has_provider_lines_in_timeline"):
        failures.append(
            {
                "code": "provider_line_leak",
                "severity": "high",
                "hint": "Remove provider/author raw lines from timeline renderer.",
            }
        )
    if (scorecard.get("provider_misassignment_count") or 0) > 0:
        failures.append(
            {
                "code": "provider_misassignment",
                "severity": "high",
                "hint": "Avoid propagating low-confidence providers across unrelated events.",
            }
        )
    if (scorecard.get("patient_scope_violation_count") or 0) > 0:
        failures.append(
            {
                "code": "patient_scope_violation",
                "severity": "critical",
                "hint": "Enforce patient scope boundaries: split or trim mixed-scope event pages/citations.",
            }
        )
    if (scorecard.get("empty_surgery_entries") or 0) > 0:
        failures.append(
            {
                "code": "empty_surgery_entry",
                "severity": "high",
                "hint": "Require procedure evidence for surgery entries.",
            }
        )
    timeline_count = scorecard.get("timeline_entry_count") or 0
    timeline_limit = scorecard.get("timeline_limit") or 80
    if timeline_count >= timeline_limit:
        failures.append(
            {
                "code": "timeline_overflow",
                "severity": "medium",
                "hint": "Increase minimum-substance threshold; suppress low-value events.",
            }
        )
    return failures


def build_critique_packet(case_id: str, source_pdf: Path, eval_dir: Path) -> dict[str, Any]:
    scorecard_path = eval_dir / "scorecard.json"
    output_pdf = eval_dir / "output.pdf"
    if not scorecard_path.exists():
        raise FileNotFoundError(f"Missing scorecard at {scorecard_path}")
    if not output_pdf.exists():
        raise FileNotFoundError(f"Missing output PDF at {output_pdf}")
    if not source_pdf.exists():
        raise FileNotFoundError(f"Missing source PDF at {source_pdf}")

    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    failures = failure_taxonomy(scorecard)
    source_text = extract_pdf_text(source_pdf)
    output_text = extract_pdf_text(output_pdf)

    packet = {
        "case_id": case_id,
        "source_pdf": str(source_pdf),
        "output_pdf": str(output_pdf),
        "overall_pass": bool(scorecard.get("overall_pass")),
        "failures": failures,
        "scorecard": scorecard,
    }
    (eval_dir / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    (eval_dir / "critique_packet.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
    (eval_dir / "source_text.txt").write_text(source_text, encoding="utf-8")
    (eval_dir / "output_text.txt").write_text(output_text, encoding="utf-8")

    lines = [
        f"# Critique Packet: {case_id}",
        "",
        f"- Overall pass: `{packet['overall_pass']}`",
        f"- Failures: `{len(failures)}`",
        "",
        "## Failure Summary",
    ]
    if failures:
        for item in failures:
            lines.append(f"- `{item['severity']}` `{item['code']}`: {item['hint']}")
    else:
        lines.append("- No failures detected by deterministic gates.")

    lines += [
        "",
        "## Scorecard",
        "```json",
        json.dumps(scorecard, indent=2),
        "```",
    ]
    (eval_dir / "critique_packet.md").write_text("\n".join(lines), encoding="utf-8")
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(description="Build critique packet from a run output and scorecard.")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--eval-dir", help="Defaults to data/evals/<case-id>.")
    args = parser.parse_args()

    eval_dir = Path(args.eval_dir) if args.eval_dir else (Path(__file__).resolve().parents[1] / "data" / "evals" / args.case_id)
    packet = build_critique_packet(args.case_id, Path(args.source_pdf), eval_dir)
    print(json.dumps({"case_id": packet["case_id"], "overall_pass": packet["overall_pass"], "failures": len(packet["failures"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
