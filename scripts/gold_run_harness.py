from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_case import run_case


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_acceptance(evidence_graph: Path, pdf_path: Path, out_path: Path) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "verify_litigation_export_acceptance.py"),
        "--evidence-graph",
        str(evidence_graph),
        "--pdf",
        str(pdf_path),
        "--out",
        str(out_path),
    ]
    completed = subprocess.run(cmd, cwd=str(ROOT), check=False, capture_output=True, text=True)
    payload = _read_json(out_path)
    payload["exit_code"] = int(completed.returncode)
    return payload


def _extract_gate_signature(acceptance: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [c for c in (acceptance.get("checks") or []) if isinstance(c, dict)]
    sig: list[dict[str, Any]] = []
    for c in checks:
        sig.append(
            {
                "name": str(c.get("name") or ""),
                "pass": bool(c.get("PASS")),
                "outcome": str(c.get("outcome") or ""),
            }
        )
    return sig


def _extract_pdf_text(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def _mediation_pdf_leak_report(pdf_path: Path) -> dict[str, Any]:
    text = _extract_pdf_text(pdf_path)
    required = [
        "MEDICAL SEVERITY PROFILE",
        "MEDIATION EXPORT (NO VALUATION MODEL)",
        "Profile derived from documented treatment progression and objective findings only; no valuation modeling applied.",
    ]
    banned_tokens = [
        "CASE SEVERITY INDEX",
        "base_csi",
        "risk_adjusted",
        "score_0_100",
        "weights",
        "penalty_total",
    ]
    missing_required = [t for t in required if t not in text]
    leaked_tokens = [t for t in banned_tokens if t in text]
    section_value_format = False
    i = text.find("MEDICAL SEVERITY PROFILE")
    if i >= 0:
        section = text[i : i + 1200]
        # severity-line valuation style like "severity ... X/10" or "CSI ... X/10"
        section_value_format = bool(re.search(r"(severity|csi)[^\n]{0,60}\b\d+(?:\.\d+)?/10\b", section, re.I))
    return {
        "missing_required_tokens": missing_required,
        "leaked_banned_tokens": leaked_tokens,
        "has_severity_value_format": section_value_format,
        "pass": (len(missing_required) == 0 and len(leaked_tokens) == 0 and not section_value_format),
    }


def _run_once(packet: Path, case_id: str, run_label: str, export_mode: str) -> dict[str, Any]:
    payload = run_case(packet, case_id=case_id, run_label=run_label, export_mode=export_mode)
    eval_dir = ROOT / "data" / "evals" / case_id
    evidence_graph = eval_dir / "evidence_graph.json"
    pdf_path = eval_dir / f"output_{export_mode}.pdf"
    acceptance_path = eval_dir / "acceptance_check.json"
    acceptance = _run_acceptance(evidence_graph, pdf_path, acceptance_path)
    mediation_pdf_check = _mediation_pdf_leak_report(pdf_path) if export_mode == "MEDIATION" else {"pass": True}

    return {
        "case_id": case_id,
        "run_id": str(payload.get("run_id") or run_label),
        "overall_pass": bool(payload.get("overall_pass")),
        "qa_pass": bool(payload.get("qa_pass")),
        "artifact_manifest_ok": bool(payload.get("artifact_manifest_ok")),
        "acceptance_all_pass": bool(acceptance.get("all_pass")),
        "acceptance_exit_code": int(acceptance.get("exit_code", 1)),
        "projection_entries": int(payload.get("projection_entries") or 0),
        "gaps_count": int(payload.get("gaps_count") or 0),
        "gate_signature": _extract_gate_signature(acceptance),
        "mediation_pdf_check": mediation_pdf_check,
        "artifacts": {
            "eval_dir": str(eval_dir),
            "output_pdf": str(pdf_path),
            "evidence_graph": str(evidence_graph),
            "acceptance_check": str(acceptance_path),
        },
    }


def _parity_summary(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    same = True
    reasons: list[str] = []

    keys_to_match = [
        "overall_pass",
        "qa_pass",
        "artifact_manifest_ok",
        "acceptance_all_pass",
        "projection_entries",
        "gaps_count",
    ]
    for key in keys_to_match:
        if a.get(key) != b.get(key):
            same = False
            reasons.append(f"{key}: {a.get(key)} != {b.get(key)}")

    if a.get("gate_signature") != b.get("gate_signature"):
        same = False
        reasons.append("gate_signature differs")
    if a.get("mediation_pdf_check") != b.get("mediation_pdf_check"):
        same = False
        reasons.append("mediation_pdf_check differs")
    if not bool(a.get("mediation_pdf_check", {}).get("pass", True)) or not bool(b.get("mediation_pdf_check", {}).get("pass", True)):
        same = False
        reasons.append("mediation_pdf_check failed")

    return {
        "deterministic_parity": same,
        "reasons": reasons,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a deterministic two-pass gold harness and emit a summary JSON.")
    ap.add_argument("--packet", required=True, type=Path, help="Path to packet PDF")
    ap.add_argument("--case-id", required=True, help="Base case id for eval output")
    ap.add_argument("--out", type=Path, default=None, help="Output summary JSON path")
    ap.add_argument("--export-mode", required=True, choices=["INTERNAL", "MEDIATION"])
    args = ap.parse_args()

    packet = args.packet.resolve()
    if packet.is_dir():
        packet = packet / "packet.pdf"
    if not packet.exists():
        raise FileNotFoundError(f"Packet not found: {packet}")

    run_a = _run_once(packet, case_id=f"{args.case_id}_a", run_label=f"{args.case_id}_gold_a", export_mode=args.export_mode)
    run_b = _run_once(packet, case_id=f"{args.case_id}_b", run_label=f"{args.case_id}_gold_b", export_mode=args.export_mode)
    parity = _parity_summary(run_a, run_b)

    summary = {
        "schema_version": "gold_run_harness.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "packet": str(packet),
        "case_id_base": args.case_id,
        "export_mode": args.export_mode,
        "run_a": run_a,
        "run_b": run_b,
        "parity": parity,
    }

    out_path = args.out or (ROOT / "data" / "evals" / f"{args.case_id}_gold_summary.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_path), "deterministic_parity": parity["deterministic_parity"], "reasons": parity["reasons"]}, indent=2))

    raise SystemExit(0 if parity["deterministic_parity"] else 1)


if __name__ == "__main__":
    main()
