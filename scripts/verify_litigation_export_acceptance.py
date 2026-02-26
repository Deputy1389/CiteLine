from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _event_type_value(event: dict[str, Any]) -> str:
    et = event.get("event_type")
    if isinstance(et, dict):
        return str(et.get("value") or "")
    return str(et or "")


def _export_status_from_pdf(pdf_text: str) -> str | None:
    m = re.search(r"Export Status\s*=\s*(VERIFIED|REVIEW_RECOMMENDED|BLOCKED)", pdf_text, re.I)
    return m.group(1).upper() if m else None


def _check_a_gap_statement_truth(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    gaps = list(eg.get("gaps") or [])
    max_gap = max([int(g.get("duration_days") or 0) for g in gaps if isinstance(g, dict)] or [0])
    says_no = bool(re.search(r"No computed global treatment gaps >45 days", pdf_text, re.I))
    says_gap = bool(re.search(r"gaps?\s*(?:detected|>45 days|identified)", pdf_text, re.I))
    passed = (says_no and max_gap <= 45) or ((not says_no) and (max_gap > 45) and says_gap)
    return {
        "name": "A_gap_statement_truth",
        "max_gap_days": max_gap,
        "pdf_says_no_gaps_gt45": says_no,
        "pdf_mentions_gap": says_gap,
        "PASS": passed,
    }


def _check_b_pt_count_consistency(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    pt_ledger = [r for r in (ext.get("pt_encounters") or []) if isinstance(r, dict) and str(r.get("source") or "primary") == "primary"]
    computed = len(pt_ledger)
    shown = [int(x) for x in re.findall(r"PT visits\s*\(Verified\)\s*:\s*(\d+)\s+encounters", pdf_text, re.I)]
    status = _export_status_from_pdf(pdf_text)
    consistent = (not shown) or all(n == computed for n in shown)
    passed = consistent or status in {"REVIEW_RECOMMENDED", "BLOCKED"}
    return {
        "name": "B_pt_count_consistency",
        "pt_events_computed_primary": computed,
        "pt_verified_counts_in_pdf": shown,
        "export_status": status,
        "PASS": passed,
    }


def _check_pt_count_defensible(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    pt_ledger = [r for r in (ext.get("pt_encounters") or []) if isinstance(r, dict) and str(r.get("source") or "primary") == "primary"]
    pt_reported = [r for r in (ext.get("pt_count_reported") or []) if isinstance(r, dict)]
    ledger_rows = len(pt_ledger)
    verified_matches = [int(x) for x in re.findall(r"PT visits\s*\(Verified\)\s*:\s*(\d+)\s+encounters", pdf_text, re.I)]
    reported_matches = [int(x) for x in re.findall(r"PT visits\s*\(Reported(?: in records)?\)\s*:\s*(\d+)\b", pdf_text, re.I)]
    reported_labeled = bool(re.search(r"PT visits\s*\(Reported(?: in records)?\)", pdf_text, re.I))
    has_ledger_section = bool(re.search(r"\bPT Visit Ledger\b", pdf_text, re.I))
    status = _export_status_from_pdf(pdf_text)
    reported_vals = sorted({int(r.get("reported_count") or 0) for r in pt_reported if int(r.get("reported_count") or 0) > 0})
    pages_by_num: dict[int, str] = {}
    for p in (eg.get("pages") or []):
        if not isinstance(p, dict):
            continue
        try:
            pages_by_num[int(p.get("page_number") or 0)] = str(p.get("page_type") or "")
        except Exception:
            continue
    clinical_note_rows = []
    for row in pt_ledger:
        try:
            pg = int(row.get("page_number") or 0)
        except Exception:
            continue
        ptype = pages_by_num.get(pg, "")
        if "clinical_note" in ptype.lower():
            clinical_note_rows.append({"page_number": pg, "page_type": ptype, "encounter_date": row.get("encounter_date")})

    verified_ok = (not verified_matches) or all(v == ledger_rows for v in verified_matches)
    ledger_backs_verified = (not verified_matches) or (has_ledger_section and ledger_rows >= max(verified_matches))
    reported_ok = (not reported_matches) or reported_labeled
    severe_variance = bool(reported_vals and ledger_rows < 3 and max(reported_vals) >= 10)
    severe_variance_status_ok = (not severe_variance) or status in {"REVIEW_RECOMMENDED", "BLOCKED"}
    zero_verified_block = not (ledger_rows == 0 and verified_matches)
    no_clinical_note_pt = len(clinical_note_rows) == 0
    passed = verified_ok and ledger_backs_verified and reported_ok and severe_variance_status_ok and zero_verified_block and no_clinical_note_pt
    return {
        "name": "PT_count_defensible",
        "pdf_verified_pt_count": (verified_matches[0] if verified_matches else None),
        "pdf_reported_pt_count": (reported_matches[0] if reported_matches else None),
        "pt_events_computed_primary": ledger_rows,
        "ledger_rows": ledger_rows,
        "reported_counts_evidence_graph": reported_vals,
        "has_pt_visit_ledger": has_ledger_section,
        "severe_variance_flag": severe_variance,
        "pt_encounter_clinical_note_rows": clinical_note_rows[:10],
        "export_status": status,
        "PASS": passed,
    }


def _check_pt_same_day_inflation_guard(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    recon = (ext.get("pt_reconciliation") or {}) if isinstance(ext.get("pt_reconciliation"), dict) else {}
    anomaly = (recon.get("date_concentration_anomaly") or {}) if isinstance(recon.get("date_concentration_anomaly"), dict) else {}
    triggered = bool(anomaly.get("triggered"))
    verified = int(recon.get("verified_pt_count") or 0)
    max_date = anomaly.get("max_date")
    max_count = int(anomaly.get("max_date_count") or 0)
    max_ratio = float(anomaly.get("max_date_ratio") or 0.0)
    export_status = _export_status_from_pdf(pdf_text)
    visible_warning = bool(re.search(r"PT date concentration anomaly:", pdf_text, re.I))
    passed = (not triggered) or (export_status in {"REVIEW_RECOMMENDED", "BLOCKED"} and visible_warning)
    return {
        "name": "PT_same_day_inflation_guard",
        "pt_verified_count": verified,
        "max_date": max_date,
        "max_date_count": max_count,
        "max_date_ratio": round(max_ratio, 4),
        "anomaly_triggered": triggered,
        "export_status": export_status,
        "visible_pdf_warning": visible_warning,
        "PASS": passed,
    }


def _check_c_high_volume_provider_requirement(pdf_text: str) -> dict[str, Any]:
    lines = pdf_text.splitlines()
    count_pat = re.compile(r"(PT visits:\s*(\d+)\s+encounters|Aggregated PT sessions \((\d+)\s+encounters\))", re.I)
    badprov = re.compile(r"\b(Unknown|Provider not clearly identified)\b", re.I)
    okprov = re.compile(r"Provider not stated in source record", re.I)
    violations: list[dict[str, Any]] = []
    for i, line in enumerate(lines):
        m = count_pat.search(line)
        if not m:
            continue
        n = int(m.group(2) or m.group(3) or "0")
        if n <= 20:
            continue
        window = " | ".join(lines[max(0, i - 2) : i + 3])
        if badprov.search(window) and not okprov.search(window):
            violations.append({"line": i + 1, "count": n, "window": window[:500]})
    return {
        "name": "C_high_volume_provider_requirement",
        "threshold": 20,
        "violations": violations,
        "PASS": len(violations) == 0,
    }


def _check_d_procedure_date_requirement(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    status = _export_status_from_pdf(pdf_text)
    has_undated_proc = bool(re.search(r"Undated.*(Procedure|Injection|Epidural|ESI)", pdf_text, re.I))
    events = [e for e in (eg.get("events") or []) if isinstance(e, dict)]
    proc_events = [e for e in events if "procedure" in _event_type_value(e).lower()]
    passed = (not has_undated_proc) or status in {"REVIEW_RECOMMENDED", "BLOCKED"}
    return {
        "name": "D_procedure_date_requirement",
        "pdf_has_undated_procedure": has_undated_proc,
        "procedure_events_json": len(proc_events),
        "export_status": status,
        "PASS": passed,
    }


def _check_e_no_garbage_text(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    status = _export_status_from_pdf(pdf_text)
    pats = [
        re.compile(r"lorem ipsum", re.I),
        re.compile(r"\bvery partner example rate remain better letter vehicle just\b", re.I),
    ]
    hits: list[dict[str, Any]] = []
    for e in (eg.get("events") or []):
        if not isinstance(e, dict):
            continue
        for field in ("facts", "diagnoses", "exam_findings", "procedures", "treatment_plan"):
            for f in (e.get(field) or []):
                txt = (f.get("text") if isinstance(f, dict) else "") or ""
                if any(p.search(txt) for p in pats):
                    hits.append({"event_id": e.get("event_id"), "field": field, "text": txt[:200]})
    visible_integrity_notice = bool(re.search(r"Export Status\s*=\s*(REVIEW_RECOMMENDED|BLOCKED)", pdf_text, re.I))
    passed = (len(hits) == 0) or (status in {"REVIEW_RECOMMENDED", "BLOCKED"} and visible_integrity_notice)
    return {
        "name": "E_no_garbage_text",
        "garbage_hits": len(hits),
        "samples": hits[:5],
        "export_status": status,
        "visible_integrity_notice": visible_integrity_notice,
        "PASS": passed,
    }


def _provider_resolution_marker(eg: dict[str, Any]) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    marker = ext.get("provider_resolution_quality")
    return {
        "name": "new_worker_marker_provider_resolution_quality",
        "present": marker is not None,
        "value": marker,
        "PASS": marker is not None,
    }


def _check_provider_resolution_quality(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    marker = ext.get("provider_resolution_quality") or {}
    pt = (marker.get("pt_ledger") or {}) if isinstance(marker, dict) else {}
    verified_count = int(((ext.get("pt_reconciliation") or {}).get("verified_pt_count")) or 0)
    facility_ratio = float(pt.get("pt_facility_resolved_ratio") or (1.0 if verified_count == 0 else 0.0))
    provider_ratio = float(pt.get("pt_provider_resolved_ratio") or (1.0 if verified_count == 0 else 0.0))
    gate = (pt.get("pt_provider_facility_gate") or {}) if isinstance(pt, dict) else {}
    gate_status = str(gate.get("status") or "warn").upper()
    export_status = _export_status_from_pdf(pdf_text)
    pass_gate = True
    if verified_count >= 10:
        if facility_ratio < 0.50:
            pass_gate = export_status == "BLOCKED"
        elif facility_ratio < 0.90:
            pass_gate = export_status in {"REVIEW_RECOMMENDED", "BLOCKED"}
    return {
        "name": "provider_resolution_quality",
        "pt_ledger_rows_total": int(pt.get("pt_ledger_rows_total") or verified_count),
        "pt_facility_resolved": int(pt.get("pt_facility_resolved") or 0),
        "pt_provider_resolved": int(pt.get("pt_provider_resolved") or 0),
        "pt_facility_resolved_ratio": round(facility_ratio, 4),
        "pt_provider_resolved_ratio": round(provider_ratio, 4),
        "gate_status": gate_status,
        "export_status": export_status,
        "top_unresolved_examples": list(pt.get("top_unresolved_examples") or [])[:3],
        "PASS": bool(isinstance(marker, dict) and marker) and pass_gate,
    }


def _check_claim_context_alignment(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    cca = ext.get("claim_context_alignment") or {}
    status = _export_status_from_pdf(pdf_text)
    failures = [f for f in (cca.get("failures") or []) if isinstance(f, dict)]
    blocked = [f for f in failures if str(f.get("severity") or "").upper() == "BLOCKED"]
    review = [f for f in failures if str(f.get("severity") or "").upper() == "REVIEW_REQUIRED"]
    visible_specific = bool(re.search(r"CLAIM_CONTEXT_ALIGNMENT:", pdf_text, re.I))
    pass_status = True
    if blocked:
        pass_status = status == "BLOCKED" and visible_specific
    elif review:
        pass_status = status in {"REVIEW_RECOMMENDED", "BLOCKED"} and visible_specific
    return {
        "name": "claim_context_alignment",
        "present": bool(isinstance(cca, dict) and cca),
        "claims_total": int(cca.get("claims_total") or 0) if isinstance(cca, dict) else 0,
        "claims_fail": int(cca.get("claims_fail") or 0) if isinstance(cca, dict) else 0,
        "export_status_claim_context": str(cca.get("export_status") or "PASS") if isinstance(cca, dict) else "MISSING",
        "blocked_failures": blocked[:5],
        "review_failures": review[:5],
        "pdf_has_specific_claim_context_lines": visible_specific,
        "export_status": status,
        "PASS": bool(isinstance(cca, dict) and cca) and pass_status,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-graph", required=True, type=Path)
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    eg = _load_json(args.evidence_graph)
    pdf_text = _pdf_text(args.pdf)

    checks = [
        _check_a_gap_statement_truth(eg, pdf_text),
        _check_b_pt_count_consistency(eg, pdf_text),
        _check_pt_count_defensible(eg, pdf_text),
        _check_pt_same_day_inflation_guard(eg, pdf_text),
        _check_c_high_volume_provider_requirement(pdf_text),
        _check_d_procedure_date_requirement(eg, pdf_text),
        _check_e_no_garbage_text(eg, pdf_text),
        _provider_resolution_marker(eg),
        _check_provider_resolution_quality(eg, pdf_text),
        _check_claim_context_alignment(eg, pdf_text),
    ]
    payload = {
        "evidence_graph": str(args.evidence_graph),
        "pdf": str(args.pdf),
        "all_pass": all(bool(c.get("PASS")) for c in checks),
        "checks": checks,
    }
    text = json.dumps(payload, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    raise SystemExit(0 if payload["all_pass"] else 1)


if __name__ == "__main__":
    main()
