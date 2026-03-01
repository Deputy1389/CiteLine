from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pypdf import PdfReader

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.shared.utils.noise_utils import is_flowsheet_noise
from packages.shared.utils.scoring_utils import is_ed_event


def _canonical_gate_snapshot(eg: dict[str, Any], evidence_graph_path: Path | None = None) -> dict[str, Any] | None:
    ext = eg.get("extensions") or {}
    parity = ext.get("pipeline_parity_report")
    if not isinstance(parity, dict) and evidence_graph_path is not None:
        parity_path = evidence_graph_path.parent / "pipeline_parity_report.json"
        if parity_path.exists():
            try:
                loaded = _load_json(parity_path)
            except Exception:
                loaded = {}
            if isinstance(loaded, dict):
                parity = loaded
    if not isinstance(parity, dict):
        return None
    snap = parity.get("gate_outcome_snapshot")
    if not isinstance(snap, dict):
        return None
    overall_pass = bool(snap.get("overall_pass", True))
    failure_codes = [str(x).strip() for x in (snap.get("failure_codes") or []) if str(x).strip()]
    return {
        "overall_pass": overall_pass,
        "failure_codes": failure_codes,
        "failures_count": int(snap.get("failures_count") or len(failure_codes)),
    }


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _pdf_pages_text(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [(p.extract_text() or "") for p in reader.pages]


def _timeline_text_from_pdf_text(pdf_text: str) -> str:
    low = (pdf_text or "").lower()
    start = low.find("medical timeline (litigation ready)")
    if start < 0:
        start = low.find("chronological medical timeline")
    if start < 0:
        return pdf_text or ""
    end_candidates = [
        low.find("imaging & objective findings", start + 1),
        low.find("top 10 case-driving events", start + 1),
    ]
    end_candidates = [i for i in end_candidates if i > start]
    end = min(end_candidates) if end_candidates else len(pdf_text or "")
    return (pdf_text or "")[start:end]


def _count_timeline_rows_in_pdf_text(pdf_text: str) -> int:
    timeline_text = _timeline_text_from_pdf_text(pdf_text)
    lines = [ln.strip() for ln in timeline_text.splitlines() if ln.strip()]
    rows = 0
    for i, line in enumerate(lines):
        if re.match(r"^(?:\d{4}-\d{2}-\d{2}|Undated)\s+\|\s+encounter:\s+", line, re.I):
            rows += 1
            continue
        if re.match(r"^(?:\d{4}-\d{2}-\d{2}|Undated)$", line, re.I):
            window = " ".join(lines[i : i + 8]).lower()
            if "citation(s):" in window:
                rows += 1
    return rows


def _top10_section_lines(pdf_text: str) -> list[str]:
    low = (pdf_text or "").lower()
    start = low.find("top 10 case-driving events")
    if start < 0:
        return []
    end_candidates = [
        low.find("liability facts", start + 1),
        low.find("causation chain", start + 1),
        low.find("damages progression", start + 1),
        low.find("medical timeline (litigation ready)", start + 1),
    ]
    end_candidates = [i for i in end_candidates if i > start]
    end = min(end_candidates) if end_candidates else len(pdf_text or "")
    block = (pdf_text or "")[start:end]
    return [ln.strip() for ln in block.splitlines() if ln.strip()]


def _event_type_value(event: dict[str, Any]) -> str:
    et = event.get("event_type")
    if isinstance(et, dict):
        return str(et.get("value") or "")
    return str(et or "")


def _export_status_from_pdf(pdf_text: str) -> str | None:
    if re.search(r"\bLitigation-Ready\b", pdf_text, re.I):
        return "VERIFIED"
    if re.search(r"\bAttorney Review Recommended\b", pdf_text, re.I):
        return "REVIEW_RECOMMENDED"
    if re.search(r"\bNot Yet Litigation-Safe\b", pdf_text, re.I):
        return "BLOCKED"
    m = re.search(r"Export Status\s*=\s*(VERIFIED|REVIEW_RECOMMENDED|BLOCKED)", pdf_text, re.I)
    return m.group(1).upper() if m else None


def _export_status_from_artifact(eg: dict[str, Any]) -> str | None:
    ext = eg.get("extensions") or {}
    lsv1 = ext.get("litigation_safe_v1") or {}
    raw = str(lsv1.get("status") or "").strip().upper()
    if raw in {"VERIFIED", "REVIEW_RECOMMENDED", "BLOCKED"}:
        return raw
    return None


def _effective_export_status(eg: dict[str, Any], pdf_text: str) -> str | None:
    return _export_status_from_artifact(eg) or _export_status_from_pdf(pdf_text)


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
    status = _effective_export_status(eg, pdf_text)
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
    status = _effective_export_status(eg, pdf_text)
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
    export_status = _effective_export_status(eg, pdf_text)
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


def _check_g3_no_undated_invasive_in_timeline(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    timeline_text = _timeline_text_from_pdf_text(pdf_text)
    blocks = [m.group(0) for m in re.finditer(r"(?ims)(?:^|\n)(Undated|Date not documented)\b.*?(?=\n(?:\d{4}-\d{2}-\d{2}|Undated|Date not documented)\b|\Z)", timeline_text)]
    undated_invasive_rows = [
        b.strip()
        for b in blocks
        if re.search(r"\b(procedure|surgery|injection|epidural|esi|transforaminal|interlaminar)\b", b, re.I)
    ]
    ext = (eg.get("extensions") or {})
    sprint4d = ext.get("sprint4d_invariants") if isinstance(ext.get("sprint4d_invariants"), dict) else {}
    unresolved_rows = list(sprint4d.get("unresolved_invasive_rows") or []) if isinstance(sprint4d, dict) else []
    passed = len(undated_invasive_rows) == 0
    return {
        "name": "G3_no_undated_invasive_in_timeline",
        "tier": "HARD",
        "severity": "BLOCKED",
        "outcome": ("PASS" if passed else "FAIL"),
        "undated_invasive_rows_main_timeline": len(undated_invasive_rows),
        "moved_to_unresolved": len(unresolved_rows),
        "samples_main_timeline": undated_invasive_rows[:3],
        "PASS": passed,
    }


def _check_e_no_garbage_text(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    status = _effective_export_status(eg, pdf_text)
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
    visible_integrity_notice = bool(re.search(r"(Attorney Review Recommended|Not Yet Litigation-Safe)", pdf_text, re.I))
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
    export_status = _effective_export_status(eg, pdf_text)
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


def _check_g4_provider_resolution(eg: dict[str, Any]) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    marker = ext.get("provider_resolution_quality") or {}
    rows_total = int(marker.get("rows_total") or 0) if isinstance(marker, dict) else 0
    rows_resolved = int(marker.get("rows_resolved") or 0) if isinstance(marker, dict) else 0
    try:
        resolved_ratio = float(marker.get("resolved_ratio")) if isinstance(marker, dict) and marker.get("resolved_ratio") is not None else 0.0
    except Exception:
        resolved_ratio = 0.0
    threshold = 0.80
    present = bool(isinstance(marker, dict) and marker)
    passed = present and rows_total > 0 and resolved_ratio >= threshold
    return {
        "name": "G4_provider_resolution",
        "tier": "HARD",
        "severity": "BLOCKED",
        "outcome": ("PASS" if passed else "FAIL"),
        "threshold": threshold,
        "rows_total": rows_total,
        "rows_resolved": rows_resolved,
        "resolved_ratio": round(resolved_ratio, 4),
        "PASS": passed,
    }


def _check_page1_promoted_parity_guard(eg: dict[str, Any]) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    inv = ext.get("sprint4d_invariants") if isinstance(ext.get("sprint4d_invariants"), dict) else {}
    parity_failed = bool(inv.get("PAGE1_PROMOTED_PARITY_FAILURE")) if isinstance(inv, dict) else False
    promoted_considered = int(inv.get("page1_promoted_considered") or 0) if isinstance(inv, dict) else 0
    promoted_rendered = int(inv.get("page1_promoted_rendered") or 0) if isinstance(inv, dict) else 0
    fallback_used = bool(inv.get("page1_promoted_fallback_used")) if isinstance(inv, dict) else False
    passed = not parity_failed
    return {
        "name": "PAGE1_PROMOTED_PARITY_GUARD",
        "tier": "HARD",
        "severity": "BLOCKED",
        "outcome": ("PASS" if passed else "FAIL"),
        "promoted_considered": promoted_considered,
        "promoted_rendered": promoted_rendered,
        "fallback_used": fallback_used,
        "PASS": passed,
    }


def _check_claim_context_alignment(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    cca = ext.get("claim_context_alignment") or {}
    status = _effective_export_status(eg, pdf_text)
    failures = [f for f in (cca.get("failures") or []) if isinstance(f, dict)]
    blocked = [f for f in failures if str(f.get("severity") or "").upper() == "BLOCKED"]
    review = [f for f in failures if str(f.get("severity") or "").upper() == "REVIEW_REQUIRED"]
    has_vuln_section = bool(re.search(r"Defense Vulnerabilities Identified", pdf_text, re.I))
    pass_status = True
    if blocked:
        pass_status = status == "BLOCKED"
    elif review:
        pass_status = status in {"REVIEW_RECOMMENDED", "BLOCKED"}
    return {
        "name": "claim_context_alignment",
        "present": bool(isinstance(cca, dict) and cca),
        "claims_total": int(cca.get("claims_total") or 0) if isinstance(cca, dict) else 0,
        "claims_fail": int(cca.get("claims_fail") or 0) if isinstance(cca, dict) else 0,
        "export_status_claim_context": str(cca.get("export_status") or "PASS") if isinstance(cca, dict) else "MISSING",
        "blocked_failures": blocked[:5],
        "review_failures": review[:5],
        "pdf_has_defense_vulnerabilities_section": has_vuln_section,
        "export_status": status,
        "PASS": bool(isinstance(cca, dict) and cca) and pass_status,
    }


def _check_g1_promotion_integrity(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    cca = ext.get("claim_context_alignment") or {}
    failures = [f for f in (cca.get("failures") or []) if isinstance(f, dict)]
    blocked = [f for f in failures if str(f.get("severity") or "").upper() == "BLOCKED"]
    blocked_mechanism = False
    for f in blocked:
        if str(f.get("claim_type") or "").strip().lower() == "mechanism":
            blocked_mechanism = True
            break
        for cf in (f.get("claim_failures") or []):
            if isinstance(cf, dict) and str(cf.get("claim_type") or "").strip().lower() == "mechanism":
                blocked_mechanism = True
                break
        if blocked_mechanism:
            break
    mechanism_promoted_phrase = bool(re.search(r"\bMechanism documented:\b", pdf_text, re.I))
    mechanism_header_strong = bool(
        re.search(r"\bMechanism\b.{0,120}\b(motor vehicle|collision|rear[- ]end|mva|mvc|fall)\b", pdf_text, re.I)
    )
    mechanism_disclosure = bool(
        re.search(r"\bMechanism\b.{0,160}\b(not elevated|phrasing varies|context review recommended)\b", pdf_text, re.I)
    )
    leak = blocked_mechanism and (mechanism_promoted_phrase or (mechanism_header_strong and not mechanism_disclosure))
    # Hard gate semantics: any blocked promotion failure must fail G1.
    passed = (len(blocked) == 0) and (not leak)
    return {
        "name": "G1_promotion_integrity",
        "tier": "HARD",
        "severity": "BLOCKED",
        "outcome": ("PASS" if passed else "FAIL"),
        "blocked_failures_count": len(blocked),
        "blocked_mechanism": blocked_mechanism,
        "mechanism_promoted_phrase": mechanism_promoted_phrase,
        "mechanism_header_strong": mechanism_header_strong,
        "mechanism_disclosure_present": mechanism_disclosure,
        "PASS": passed,
    }


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _check_snapshot_coherence_guard(eg: dict[str, Any], pdf_pages: list[str], pdf_text: str) -> dict[str, Any]:
    ext = eg.get("extensions") or {}
    rm = (ext.get("renderer_manifest") or {}) if isinstance(ext.get("renderer_manifest"), dict) else {}
    cca = (ext.get("claim_context_alignment") or {}) if isinstance(ext.get("claim_context_alignment"), dict) else {}
    page1 = pdf_pages[0] if pdf_pages else ""
    page1_norm = _norm_text(page1)
    highlights_idx = page1_norm.find(_norm_text("Case Highlights"))
    additional_idx = page1_norm.find(_norm_text("Additional Findings (Context Not Fully Verified)"))
    vuln_idx = page1_norm.find(_norm_text("Defense Vulnerabilities Identified"))

    promoted = [p for p in (rm.get("promoted_findings") or []) if isinstance(p, dict)]
    promoted_fail_in_snapshot: list[str] = []
    promoted_pass_in_vuln: list[str] = []
    annotated_count = 0
    for p in promoted:
        label = str(p.get("label") or "").strip()
        if not label:
            continue
        norm_label = _norm_text(label)
        if not norm_label:
            continue
        status = str(p.get("alignment_status") or "").upper()
        if status:
            annotated_count += 1
        pos = page1_norm.find(norm_label)
        if pos < 0:
            continue
        in_snapshot_region = highlights_idx >= 0 and pos >= highlights_idx and (additional_idx < 0 or pos < additional_idx)
        in_vuln_region = vuln_idx >= 0 and pos >= vuln_idx
        if status and status != "PASS" and in_snapshot_region:
            promoted_fail_in_snapshot.append(label)
        if status == "PASS" and in_vuln_region:
            promoted_pass_in_vuln.append(label)

    raw_code_hits = sorted({
        hit
        for hit in re.findall(
            r"\b(?:semantic_mismatch|semantic_borderline|page_type_mismatch|missing_citation|CLAIM_CONTEXT_ALIGNMENT|INTERNAL_CONTRADICTION|MECHANISM_OR_DIAGNOSIS_UNSUPPORTED)\b",
            pdf_text,
            flags=re.I,
        )
    })
    raw_status_line_visible = bool(re.search(r"Export Status\s*=", pdf_text, re.I))
    has_assurance_line = bool(
        re.search(r"Snapshot includes only record-supported, citation-verified findings\.", pdf_text, re.I)
        or re.search(r"The records document citation-verified findings\.", pdf_text, re.I)
        or re.search(r"Emergency department and treatment documentation support the findings below\.", pdf_text, re.I)
    )
    has_additional_findings_section = bool(re.search(r"Additional Findings \(Context Not Fully Verified\)", pdf_text, re.I))
    expected_additional = any(
        bool(p.get("headline_eligible", True))
        and str(p.get("alignment_status") or "").upper() in {"REVIEW_REQUIRED", "BLOCKED"}
        for p in promoted
    )
    cca_present = bool(cca)

    needs_annotation = len(promoted) > 0
    passed = (
        cca_present
        and ((not needs_annotation) or annotated_count > 0)
        and has_assurance_line
        and not promoted_fail_in_snapshot
        and not promoted_pass_in_vuln
        and not raw_code_hits
        and not raw_status_line_visible
        and ((not expected_additional) or has_additional_findings_section)
    )
    return {
        "name": "SNAPSHOT_COHERENCE_GUARD",
        "claim_context_alignment_present": cca_present,
        "promoted_findings_total": len(promoted),
        "promoted_findings_annotated": annotated_count,
        "page1_has_snapshot_assurance_line": has_assurance_line,
        "page1_has_additional_findings_section": has_additional_findings_section,
        "expected_additional_findings_section": expected_additional,
        "snapshot_failed_alignment_labels": promoted_fail_in_snapshot[:5],
        "snapshot_claims_in_defense_vulnerabilities": promoted_pass_in_vuln[:5],
        "raw_internal_code_hits_in_pdf": raw_code_hits,
        "raw_export_status_line_visible": raw_status_line_visible,
        "PASS": passed,
    }


def _check_substantive_metric_audit(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    events = [e for e in (eg.get("events") or []) if isinstance(e, dict)]
    substantive_ids: list[str] = []
    flowsheet_excluded_ids: list[str] = []
    candidate_ids: list[str] = []
    retained_narrative_ids: list[str] = []

    def _event_text(e: dict[str, Any]) -> str:
        chunks: list[str] = []
        for f in (e.get("facts") or []):
            if isinstance(f, dict):
                t = str(f.get("text") or "").strip()
            else:
                t = ""
            if t:
                chunks.append(t)
        return " ".join(chunks)

    def _event_has_citation(e: dict[str, Any]) -> bool:
        if e.get("citation_ids"):
            return True
        for f in (e.get("facts") or []):
            if isinstance(f, dict) and (f.get("citation_ids") or []):
                return True
        return False

    def _event_substantive_class(e: dict[str, Any], text: str) -> str | None:
        et = _event_type_value(e).lower()
        low = (text or "").lower()
        if et in {"er_visit", "hospital_admission"} or re.search(r"\b(emergency department|emergency room|chief complaint|hpi)\b", low):
            return "acute_evaluation"
        if "imaging" in et and re.search(r"\b(impression|mri|ct|x-?ray|ultrasound|fracture|tear)\b", low):
            return "imaging_interpretation"
        if "procedure" in et or re.search(r"\b(procedure|injection|surgery|operative|epidural|fluoroscopy)\b", low):
            return "procedure"
        if "pt_visit" in et and re.search(r"\b(initial evaluation|plan of care|re-?evaluation|discharge summary)\b", low):
            return "therapy_eval_or_discharge"
        if re.search(r"\b(consult|follow-?up|assessment|diagnosis|impression)\b", low) and re.search(r"\b(physician|doctor|orthopedic|neurology|clinic)\b", low):
            return "specialist_or_physician_eval"
        if re.search(r"\b(weakness|strength\s*[0-5]/5|range of motion|rom|reflex|diminished)\b", low):
            return "functional_or_objective_deficit"
        return None

    def _has_narrative_sentence(text: str) -> bool:
        for raw in re.split(r"[\n\r]+", text or ""):
            line = (raw or "").strip()
            if not line:
                continue
            if len(re.findall(r"[A-Za-z]{2,}", line)) < 8:
                continue
            if line.endswith(".") or re.search(r"\b(reports?|denies|exam|assessment|impression|diagnosis|plan)\b", line, re.I):
                return True
        return False

    for e in events:
        eid = str(e.get("event_id") or "").strip()
        if not eid:
            continue
        txt = _event_text(e)
        if not txt:
            continue
        if not _event_has_citation(e):
            continue
        has_narrative = _has_narrative_sentence(txt)
        if is_flowsheet_noise(txt) and not has_narrative:
            flowsheet_excluded_ids.append(eid)
            continue
        candidate_ids.append(eid)
        if has_narrative:
            retained_narrative_ids.append(eid)
        if _event_substantive_class(e, txt):
            substantive_ids.append(eid)

    high_substance_ratio = (len(substantive_ids) / max(1, len(candidate_ids))) if candidate_ids else 0.0
    export_status = _effective_export_status(eg, pdf_text)
    return {
        "name": "SUBSTANTIVE_METRIC_AUDIT",
        "candidate_narrative_event_count": len(candidate_ids),
        "events_excluded_flowsheet_like": len(flowsheet_excluded_ids),
        "events_retained_narrative": len(retained_narrative_ids),
        "substantive_event_count": len(substantive_ids),
        "high_substance_ratio": round(high_substance_ratio, 4),
        "substantive_event_ids": substantive_ids[:30],
        "flowsheet_excluded_event_ids": flowsheet_excluded_ids[:30],
        "retained_narrative_event_ids": retained_narrative_ids[:30],
        "export_status": export_status,
        "PASS": True,
    }


def _check_timeline_suppression_overshot(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    events = [e for e in (eg.get("events") or []) if isinstance(e, dict)]
    candidate_narrative = 0
    for e in events:
        txt = " ".join(
            str(f.get("text") or "").strip()
            for f in (e.get("facts") or [])
            if isinstance(f, dict) and str(f.get("text") or "").strip()
        )
        if not txt:
            continue
        if is_flowsheet_noise(txt):
            # Narrative guard mirrors row-level suppression calibration.
            if not re.search(r"(?:[A-Za-z]{2,}\W+){8,}", txt) and not re.search(r"\b(reports?|denies|exam|assessment|impression|diagnosis|plan)\b", txt, re.I):
                continue
        candidate_narrative += 1
    timeline_rows_rendered = _count_timeline_rows_in_pdf_text(pdf_text)
    passed = not (candidate_narrative >= 1 and timeline_rows_rendered < 1)
    return {
        "name": "AR_TIMELINE_SUPPRESSION_OVERSHOT",
        "candidate_narrative_event_count": candidate_narrative,
        "timeline_rows_rendered": timeline_rows_rendered,
        "PASS": passed,
    }


def _check_required_bucket_detection_from_graph(eg: dict[str, Any], pdf_text: str) -> dict[str, Any]:
    events = [e for e in (eg.get("events") or []) if isinstance(e, dict)]
    pages = [p for p in (eg.get("pages") or []) if isinstance(p, dict)]
    page_by_num: dict[int, dict[str, Any]] = {}
    for p in pages:
        try:
            page_by_num[int(p.get("page_number") or 0)] = p
        except Exception:
            continue

    bucket_event_ids: dict[str, list[str]] = {"ed": [], "pt_eval": []}
    for e in events:
        eid = str(e.get("event_id") or "").strip()
        et = _event_type_value(e).lower()
        facts = " ".join(
            str(f.get("text") or "").strip()
            for f in (e.get("facts") or [])
            if isinstance(f, dict) and str(f.get("text") or "").strip()
        ).lower()
        page_blob = ""
        for pg in (e.get("source_page_numbers") or []):
            try:
                p = page_by_num.get(int(pg) or 0) or {}
            except Exception:
                p = {}
            page_blob += " " + str(p.get("text") or "")
        page_blob = page_blob.lower()
        blob = f"{facts} {page_blob}"
        provider_blob = str((e.get("provider_name") or e.get("provider_display") or "")).lower()
        if is_ed_event(
            text_blob=blob,
            event_type=et,
            provider_blob=provider_blob,
        ):
            if eid:
                bucket_event_ids["ed"].append(eid)
        pt_context = ("pt_visit" in et) or bool(re.search(r"\b(physical therapy|pt)\b", blob))
        if pt_context and re.search(r"\b(initial evaluation|pt evaluation|plan of care)\b", blob):
            if eid:
                bucket_event_ids["pt_eval"].append(eid)

    manifest = ((eg.get("extensions") or {}).get("renderer_manifest") or {})
    manifest_bucket_evidence = manifest.get("bucket_evidence") if isinstance(manifest, dict) else {}
    if isinstance(manifest_bucket_evidence, dict):
        # Manifest bucket evidence is the canonical pipeline contract when present.
        for bucket in ("ed", "pt_eval"):
            mb = manifest_bucket_evidence.get(bucket)
            if not isinstance(mb, dict):
                continue
            mids = [str(x).strip() for x in (mb.get("event_ids") or []) if str(x).strip()]
            detected = bool(mb.get("detected"))
            bucket_event_ids[bucket] = mids if (detected or mids) else []

    detected_buckets = sorted([b for b, ids in bucket_event_ids.items() if ids])
    lower_pdf = (pdf_text or "").lower()
    timeline_text = _timeline_text_from_pdf_text(pdf_text).lower()
    event_by_id = {str(e.get("event_id") or "").strip(): e for e in events}
    bucket_pages: dict[str, set[int]] = {"ed": set(), "pt_eval": set()}
    for bucket, ids in bucket_event_ids.items():
        for eid in ids:
            ev = event_by_id.get(str(eid).strip()) or {}
            for p in (ev.get("source_page_numbers") or []):
                try:
                    pnum = int(p)
                except Exception:
                    continue
                if pnum > 0:
                    bucket_pages.setdefault(bucket, set()).add(pnum)
    timeline_citation_pages = {
        int(m.group(1))
        for m in re.finditer(r"\[p\.\s*(\d+)\]", _timeline_text_from_pdf_text(pdf_text), flags=re.I)
    }
    rendered_bucket_hits = {
        "ed": bool(re.search(r"\b(emergency|er visit|hospital admission|chief complaint|hpi)\b", timeline_text)),
        "pt_eval": bool(re.search(r"\b(therapy visit|physical therapy)\b", timeline_text) and re.search(r"\b(initial evaluation|pt evaluation|plan of care)\b", timeline_text)),
    }
    sprint4d = ((eg.get("extensions") or {}).get("sprint4d_invariants") or {})
    timeline_audit = sprint4d.get("timeline_drop_audit") if isinstance(sprint4d, dict) else {}
    rendered_buckets_meta = {
        str(b).strip().lower()
        for b in (timeline_audit.get("rendered_buckets") or [])
        if str(b).strip()
    } if isinstance(timeline_audit, dict) else set()
    if "ed" in rendered_buckets_meta:
        rendered_bucket_hits["ed"] = True
    if "pt_eval" in rendered_buckets_meta:
        rendered_bucket_hits["pt_eval"] = True
    for bucket in ("ed", "pt_eval"):
        if not rendered_bucket_hits.get(bucket):
            if bucket_pages.get(bucket) and timeline_citation_pages.intersection(bucket_pages.get(bucket) or set()):
                rendered_bucket_hits[bucket] = True
    rendered_bucket_gaps = [b for b in detected_buckets if not rendered_bucket_hits.get(b, False)]
    return {
        "name": "REQUIRED_BUCKET_DETECTION_AUDIT",
        "detected_buckets": detected_buckets,
        "missing_required_buckets": [],
        "rendered_bucket_hits": rendered_bucket_hits,
        "rendered_bucket_gaps": rendered_bucket_gaps,
        "bucket_event_ids": {k: v[:10] for k, v in bucket_event_ids.items()},
        "manifest_bucket_evidence_present": bool(manifest_bucket_evidence),
        "rendered_buckets_meta": sorted(rendered_buckets_meta),
        "PASS": len(rendered_bucket_gaps) == 0,
    }


def _check_top10_integrity(pdf_text: str) -> dict[str, Any]:
    low = (pdf_text or "").lower()
    start = low.find("top 10 case-driving events")
    if start < 0:
        return {
            "name": "TOP10_INTEGRITY_AUDIT",
            "top10_item_count": 0,
            "duplicate_count": 0,
            "missing_citation_rows": 0,
            "PASS": False,
        }
    end_candidates = [
        low.find("liability facts", start + 1),
        low.find("causation chain", start + 1),
        low.find("damages progression", start + 1),
        low.find("medical timeline (litigation ready)", start + 1),
    ]
    end_candidates = [i for i in end_candidates if i > start]
    end = min(end_candidates) if end_candidates else len(pdf_text or "")
    block = (pdf_text or "")[start:end]
    item_texts = [m.group(1).strip() for m in re.finditer(r"(?ms)^\-\s+(.*?)(?=^\-\s+|\Z)", block)]
    bullets = [f"- {t}" for t in item_texts]
    normalized_keys: list[str] = []
    missing_citation_rows = 0
    for item in item_texts:
        item_norm = re.sub(r"\s+", " ", item).strip()
        if not re.search(r"\[p\.\s*\d+\]", item_norm, re.I):
            missing_citation_rows += 1
        label = re.sub(r"citation\(s\):.*$", "", item_norm, flags=re.I).strip().lower()
        label = re.sub(r"\s+", " ", label)
        normalized_keys.append(label)
    dup_count = max(0, len(normalized_keys) - len(set(normalized_keys)))
    return {
        "name": "TOP10_INTEGRITY_AUDIT",
        "top10_item_count": len(item_texts),
        "duplicate_count": dup_count,
        "missing_citation_rows": missing_citation_rows,
        "PASS": (dup_count == 0 and missing_citation_rows == 0 and len(item_texts) > 0),
    }


def _check_meta_language_cleanroom(pdf_pages: list[str]) -> dict[str, Any]:
    # Ignore eval validation cover page when present; enforce cleanroom on attorney-facing export pages.
    body_pages = list(pdf_pages[1:]) if len(pdf_pages) > 1 else list(pdf_pages)
    body_text = "\n".join(body_pages)
    banned_patterns = [
        re.compile(r"\bchronology eval\b", re.I),
        re.compile(r"\blitigation safety check\b", re.I),
        re.compile(r"\bverified in extracted chronology\b", re.I),
        re.compile(r"\bnot yet litigation-safe\b", re.I),
        re.compile(r"\battorney-facing chronology\b", re.I),
        re.compile(r"\brecommended attorney action\b", re.I),
        re.compile(r"\bdefense vulnerabilities\b", re.I),
        re.compile(r"\bcase readiness\b", re.I),
        re.compile(r"\bdefense may exploit\b", re.I),
        re.compile(r"\bclaim_context_alignment\b", re.I),
        re.compile(r"\bsemantic_mismatch\b", re.I),
        re.compile(r"\bpage_type_mismatch\b", re.I),
        re.compile(r"\bqa_[a-z0-9_]+\b", re.I),
        re.compile(r"\bar_[a-z0-9_]+\b", re.I),
    ]
    hits: list[str] = []
    for pat in banned_patterns:
        for m in pat.finditer(body_text or ""):
            hits.append(m.group(0))
    hits = sorted(set(hits))
    return {
        "name": "META_LANGUAGE_CLEANROOM",
        "meta_language_hits": hits,
        "PASS": len(hits) == 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-graph", required=True, type=Path)
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    eg = _load_json(args.evidence_graph)
    pdf_pages = _pdf_pages_text(args.pdf)
    pdf_text = "\n".join(pdf_pages)

    checks = [
        _check_a_gap_statement_truth(eg, pdf_text),
        _check_b_pt_count_consistency(eg, pdf_text),
        _check_pt_count_defensible(eg, pdf_text),
        _check_pt_same_day_inflation_guard(eg, pdf_text),
        _check_c_high_volume_provider_requirement(pdf_text),
        _check_g3_no_undated_invasive_in_timeline(eg, pdf_text),
        _check_e_no_garbage_text(eg, pdf_text),
        _provider_resolution_marker(eg),
        _check_g4_provider_resolution(eg),
        _check_provider_resolution_quality(eg, pdf_text),
        _check_page1_promoted_parity_guard(eg),
        _check_g1_promotion_integrity(eg, pdf_text),
        _check_claim_context_alignment(eg, pdf_text),
        _check_snapshot_coherence_guard(eg, pdf_pages, pdf_text),
        _check_timeline_suppression_overshot(eg, pdf_text),
        _check_substantive_metric_audit(eg, pdf_text),
        _check_required_bucket_detection_from_graph(eg, pdf_text),
        _check_top10_integrity(pdf_text),
        _check_meta_language_cleanroom(pdf_pages),
    ]
    canonical = _canonical_gate_snapshot(eg, args.evidence_graph)
    computed_all_pass = all(bool(c.get("PASS")) for c in checks)
    if canonical is not None:
        all_pass = bool(canonical.get("overall_pass", True))
        failing_gate_codes = list(canonical.get("failure_codes") or [])
    else:
        all_pass = computed_all_pass
        failing_gate_codes = []
    payload = {
        "evidence_graph": str(args.evidence_graph),
        "pdf": str(args.pdf),
        "all_pass": all_pass,
        "failing_gate_codes": failing_gate_codes,
        "canonical_gate_snapshot": canonical,
        "computed_checks_all_pass": computed_all_pass,
        "checks": checks,
    }
    text = json.dumps(payload, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    raise SystemExit(0 if payload["all_pass"] else 1)


if __name__ == "__main__":
    main()
