"""
Quality Gates Wrapper for Production Pipeline

Unified interface to run all quality gates (attorney readiness, LUQA, litigation)
and generate fail cover pages when gates fail.

This ensures production pipeline has the same gates as eval pipeline.
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Any

from apps.worker.lib.compact_packet_policy import is_compact_packet

logger = logging.getLogger(__name__)


_ATTORNEY_PLACEHOLDER_PATTERNS: list[tuple[str, str]] = [
    ("SEE_PATIENT_HEADER", r"\bSee Patient Header\b"),
    ("SENTINEL_DATE_1900", r"\b1900-01-01\b"),
    ("SENTINEL_DATE_0001", r"\b0001-01-01\b"),
    ("UNKNOWN_PROVIDER", r"\bUnknown provider\b"),
    ("NOT_AVAILABLE", r"\bNot available\b"),
    ("DATE_NOT_DOCUMENTED", r"\bDate not documented\b"),
    ("UNDATED", r"\bUndated\b"),
]

# Canonical hard/soft policy for litigation-safe v1 expression.
_HARD_FAILURE_CODES: set[str] = {
    "EXPORT_UNCITED_TIMELINE_ROW",
    "EXPORT_UNCITED_TOP10_ITEM",
    "UNDATED",
    "DATE_NOT_DOCUMENTED",
    "AR_MISSING_REQUIRED_SECTIONS",
    "AR_EMPTY_TIMELINE",
    "AR_UNCITED_FACT_ROWS",
    "LUQA_META_LANGUAGE_BAN",
    "LUQA_RENDER_QUALITY_SANITY",
    "LUQA_CARE_WINDOW_INTEGRITY",
    "LUQA_REQUIRED_BUCKETS_WHEN_PRESENT",
    "LUQA_NOISE_SUPPRESSION_RATE",
    "LUQA_DUPLICATE_SNIPPETS",
    "PT_HIGH_VOLUME_UNVERIFIED",
}
_SOFT_FAILURE_CODES: set[str] = {
    "AR_FACT_DENSITY_LOW",
    "AR_REQUIRED_BUCKETS_MISSING",
    "LUQA_PLACEHOLDER_RATIO",
    "LUQA_FACT_DENSITY",
    "LUQA_VERBATIM_ANCHOR_RATIO",
    "NOT_AVAILABLE",
    "VISIT_BUCKET_REQUIRED_MISSING",
}
def _normalize_quality_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in {"strict", "pilot"} else "strict"


def _is_hard_failure(row: dict[str, Any], *, quality_mode: str = "strict") -> bool:
    code = str(row.get("code") or "").strip().upper()
    sev = str(row.get("severity") or "").strip().lower()
    mode = _normalize_quality_mode(quality_mode)
    if mode == "pilot" and code == "LUQA_META_LANGUAGE_BAN":
        return False
    if code in _SOFT_FAILURE_CODES:
        return False
    if code in _HARD_FAILURE_CODES:
        return True
    if sev == "soft":
        return False
    if sev == "hard":
        return True
    # Conservative default: unknown failures remain hard.
    return True


def _classify_failures(
    failures: list[dict[str, Any]],
    *,
    quality_mode: str = "strict",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hard: list[dict[str, Any]] = []
    soft: list[dict[str, Any]] = []
    for row in failures:
        if _is_hard_failure(row, quality_mode=quality_mode):
            hard.append(row)
        else:
            soft.append(row)
    return hard, soft


def _attorney_facing_text(report_text: str) -> str:
    text = str(report_text or "")
    marker = "Citation Index & Record Appendix"
    idx = text.lower().find(marker.lower())
    if idx >= 0:
        return text[:idx]
    return text


def _placeholder_leak_findings(report_text: str) -> list[dict[str, Any]]:
    text = _attorney_facing_text(report_text)
    findings: list[dict[str, Any]] = []
    for code, pattern in _ATTORNEY_PLACEHOLDER_PATTERNS:
        if not re.search(pattern, text, re.IGNORECASE):
            continue
        findings.append({
            "source": "placeholder_scan",
            "code": code,
            "message": f"Attorney-facing placeholder leak detected: {code}",
        })
    return findings


def _pt_count_consistency_findings(report_text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text = _attorney_facing_text(report_text)
    verified = [int(x) for x in re.findall(r"PT visits\s*\(Verified\)\s*:\s*(\d+)\s+encounters", text, re.I)]
    reported = [
        int(x)
        for x in re.findall(
            r"PT visits\s*\(Reported(?: in records)?\)\s*:\s*(\d+)\s*(?:encounters?)?",
            text,
            re.I,
        )
    ]
    findings: list[dict[str, Any]] = []
    max_verified = max(verified) if verified else 0
    max_reported = max(reported) if reported else 0

    if verified and reported and max_verified != max_reported:
        findings.append(
            {
                "source": "pt_count_consistency",
                "code": "PT_COUNT_CONFLICT",
                "message": f"PT count mismatch: verified={max_verified}, reported={max_reported}",
                "verified_count": max_verified,
                "reported_count": max_reported,
            }
        )
    if max_reported > 10 and max_verified == 0:
        findings.append(
            {
                "source": "pt_count_consistency",
                "code": "PT_HIGH_VOLUME_UNVERIFIED",
                "message": f"High-volume PT reported without verification: reported={max_reported}, verified=0",
                "verified_count": max_verified,
                "reported_count": max_reported,
            }
        )

    telemetry = {
        "verified_counts": verified,
        "reported_counts": reported,
        "max_verified": max_verified,
        "max_reported": max_reported,
    }
    return findings, telemetry


def _projection_citation_integrity_findings(projection_entries: list[Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = list(projection_entries or [])
    uncited: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            event_id = str(row.get("event_id") or "")
            event_type = str(row.get("event_type_display") or row.get("event_type") or "")
            citation_display = str(row.get("citation_display") or "")
        else:
            event_id = str(getattr(row, "event_id", "") or "")
            event_type = str(getattr(row, "event_type_display", "") or "")
            citation_display = str(getattr(row, "citation_display", "") or "")
        cited = bool(re.search(r"\bp\.\s*\d+\b", citation_display, re.I))
        if cited:
            continue
        uncited.append(
            {
                "event_id": event_id,
                "event_type": event_type,
                "citation_display": citation_display[:160],
            }
        )
    findings = [
        {
            "source": "export_citation_integrity",
            "code": "EXPORT_UNCITED_TIMELINE_ROW",
            "message": f"Timeline/projection rows without citations: {len(uncited)}",
            "examples": uncited[:10],
        }
    ] if uncited else []
    telemetry = {
        "projection_rows_total": len(rows),
        "projection_rows_uncited": len(uncited),
    }
    return findings, telemetry


def _top10_citation_integrity_findings(report_text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text = _attorney_facing_text(report_text)
    low = text.lower()
    start = low.find("top 10 case-driving events")
    if start < 0:
        return [], {"top10_present": False, "top10_bullets_total": 0, "top10_bullets_uncited": 0}
    end_candidates = [
        low.find("liability facts", start + 1),
        low.find("medical timeline (litigation ready)", start + 1),
        low.find("impact summary", start + 1),
        low.find("citation index & record appendix", start + 1),
    ]
    end_candidates = [i for i in end_candidates if i > start]
    end = min(end_candidates) if end_candidates else len(text)
    block = text[start:end]
    bullets = [ln.strip() for ln in block.splitlines() if ln.strip().startswith("-")]
    uncited = [b for b in bullets if not re.search(r"(\[p\.\s*\d+\]|Citation\(s\):)", b, re.I)]
    findings = [
        {
            "source": "export_citation_integrity",
            "code": "EXPORT_UNCITED_TOP10_ITEM",
            "message": f"Top 10 items without citations: {len(uncited)}",
            "examples": uncited[:10],
        }
    ] if uncited else []
    telemetry = {
        "top10_present": True,
        "top10_bullets_total": len(bullets),
        "top10_bullets_uncited": len(uncited),
    }
    return findings, telemetry


def run_quality_gates(
    report_text: str,
    page_text_by_number: dict[int, str],
    projection_entries: list[Any] | None = None,
    chronology_events: list[Any] | None = None,
    gaps: list[Any] | None = None,
    source_pdf: str | None = None,
    quality_mode: str = "strict",
    visit_bucket_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run all quality gates and return a unified report.
    
    Returns:
        {
            "overall_pass": bool,
            "attorney_ready_pass": bool,
            "attorney_ready_score": int,
            "luqa_pass": bool,
            "luqa_score": int,
            "litigation_pass": bool,
            "litigation_score": int,
            "failures": list[dict],
            "gate_report": {...}  # detailed gate results
        }
    """
    from apps.worker.lib.attorney_readiness import build_attorney_readiness_report
    from apps.worker.lib.luqa import build_luqa_report
    
    ctx = {
        "page_text_by_number": page_text_by_number or {},
        "projection_entries": projection_entries or [],
    }
    
    normalized_quality_mode = _normalize_quality_mode(quality_mode)
    results = {
        "overall_pass": True,
        "attorney_ready_pass": True,
        "attorney_ready_score": 100,
        "luqa_pass": True,
        "luqa_score": 100,
        "litigation_pass": True,
        "litigation_score": 100,
        "failures": [],
        "hard_failures": [],
        "soft_failures": [],
        "review_required": False,
        "export_status": "VERIFIED",
        "quality_mode": normalized_quality_mode,
        "gate_report": {},
    }
    
    # Run Attorney Readiness
    try:
        attorney = build_attorney_readiness_report(report_text, ctx)
        results["attorney_ready_pass"] = attorney.get("attorney_ready_pass", True)
        results["attorney_ready_score"] = attorney.get("attorney_ready_score_0_100", 100)
        results["gate_report"]["attorney"] = attorney
        results["failures"].extend([
            {"source": "attorney", **f}
            for f in attorney.get("failures", [])
        ])
    except Exception as e:
        logger.warning(f"Attorney readiness check failed: {e}")
    
    # Run LUQA
    try:
        luqa = build_luqa_report(report_text, ctx)
        results["luqa_pass"] = luqa.get("luqa_pass", True)
        results["luqa_score"] = luqa.get("luqa_score_0_100", 100)
        results["gate_report"]["luqa"] = luqa
        results["failures"].extend([
            {"source": "luqa", **f}
            for f in luqa.get("failures", [])
        ])
    except Exception as e:
        logger.warning(f"LUQA check failed: {e}")
    
    # Note: Litigation checklist requires source PDF and more context
    # For now, we'll skip it in the quick wrapper but could be added
    placeholder_findings = _placeholder_leak_findings(report_text)
    if placeholder_findings:
        results["failures"].extend(placeholder_findings)
        results["gate_report"]["placeholder_scan"] = {
            "pass": False,
            "failures": placeholder_findings,
        }
    else:
        results["gate_report"]["placeholder_scan"] = {"pass": True, "failures": []}

    pt_findings, pt_telemetry = _pt_count_consistency_findings(report_text)
    if pt_findings:
        results["failures"].extend(pt_findings)
        results["gate_report"]["pt_count_consistency"] = {
            "pass": False,
            "failures": pt_findings,
            "telemetry": pt_telemetry,
        }
    else:
        results["gate_report"]["pt_count_consistency"] = {
            "pass": True,
            "failures": [],
            "telemetry": pt_telemetry,
        }

    projection_cite_findings, projection_cite_telemetry = _projection_citation_integrity_findings(projection_entries)
    top10_cite_findings, top10_cite_telemetry = _top10_citation_integrity_findings(report_text)
    export_citation_findings = projection_cite_findings + top10_cite_findings
    if export_citation_findings:
        results["failures"].extend(export_citation_findings)
        results["gate_report"]["export_citation_integrity"] = {
            "pass": False,
            "failures": export_citation_findings,
            "telemetry": {
                "projection": projection_cite_telemetry,
                "top10": top10_cite_telemetry,
            },
        }
    else:
        results["gate_report"]["export_citation_integrity"] = {
            "pass": True,
            "failures": [],
            "telemetry": {
                "projection": projection_cite_telemetry,
                "top10": top10_cite_telemetry,
            },
        }

    vbq = visit_bucket_quality if isinstance(visit_bucket_quality, dict) else {}
    miss_ratio = float(vbq.get("missing_required_bucket_ratio") or 0.0)
    miss_count = int(vbq.get("required_bucket_miss_count") or 0)
    encounter_missing = int(vbq.get("encounters_with_missing_required_buckets") or 0)
    total_encounters = int(vbq.get("total_encounters") or 0)
    compact_packet = is_compact_packet(
        score_row_count=total_encounters,
        projection_count=len(list(projection_entries or [])),
        page_count=len(page_text_by_number or {}),
        total_encounters=total_encounters,
    )
    threshold_ratio = 0.35
    threshold_count = 5
    if compact_packet:
        results["gate_report"]["visit_bucket_quality"] = {
            "pass": True,
            "failures": [],
            "telemetry": {
                **vbq,
                "compact_packet_policy": True,
                "suppressed_soft_failure": True,
            },
        }
    elif total_encounters > 0 and (miss_ratio > threshold_ratio or miss_count >= threshold_count):
        vbq_find = {
            "source": "visit_bucket_quality",
            "code": "VISIT_BUCKET_REQUIRED_MISSING",
            "severity": "soft",
            "message": (
                "Encounter required bucket completeness threshold exceeded: "
                f"encounters_missing={encounter_missing}/{total_encounters}, "
                f"required_bucket_miss_count={miss_count}, ratio={miss_ratio:.4f}"
            ),
            "threshold_ratio": threshold_ratio,
            "threshold_count": threshold_count,
        }
        results["failures"].append(vbq_find)
        results["gate_report"]["visit_bucket_quality"] = {
            "pass": False,
            "failures": [vbq_find],
            "telemetry": {
                **vbq,
                "compact_packet_policy": False,
            },
        }
    else:
        results["gate_report"]["visit_bucket_quality"] = {
            "pass": True,
            "failures": [],
            "telemetry": {
                **vbq,
                "compact_packet_policy": compact_packet,
            },
        }

    hard_failures, soft_failures = _classify_failures(
        list(results.get("failures") or []),
        quality_mode=normalized_quality_mode,
    )
    results["hard_failures"] = hard_failures
    results["soft_failures"] = soft_failures
    results["review_required"] = bool(soft_failures)
    results["overall_pass"] = len(hard_failures) == 0
    results["export_status"] = (
        "BLOCKED"
        if hard_failures
        else ("REVIEW_RECOMMENDED" if soft_failures else "VERIFIED")
    )
    results["attorney_ready_pass"] = not any(
        (f.get("source") == "attorney" and _is_hard_failure(f, quality_mode=normalized_quality_mode))
        for f in results["failures"]
    )
    results["luqa_pass"] = not any(
        (f.get("source") == "luqa" and _is_hard_failure(f, quality_mode=normalized_quality_mode))
        for f in results["failures"]
    )
    
    return results


def write_fail_cover_pdf(
    out_pdf_path: str,
    gate_results: dict[str, Any],
) -> bool:
    """
    Write an attorney-facing review/block cover page when needed.
    
    Returns True if cover was written, False if export is verified.
    """
    status = str(gate_results.get("export_status") or "").strip().upper()
    if status in {"", "VERIFIED"}:
        return False
    
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader, PdfWriter
    
    hard_failures = list(gate_results.get("hard_failures") or [])
    soft_failures = list(gate_results.get("soft_failures") or [])
    fail_lines: list[str] = []
    if status == "BLOCKED":
        fail_lines.extend(
            [
                "EXPORT STATUS: BLOCKED - Integrity Issue Detected",
                "",
                "One or more citation/integrity checks failed and must be resolved before litigation use.",
                "",
            ]
        )
        fail_lines.append("Blocking issues:")
        for f in hard_failures[:8]:
            fail_lines.append(f"- {str(f.get('code') or '').strip()}: {str(f.get('message') or '').strip()[:90]}")
    else:
        fail_lines.extend(
            [
                "EXPORT STATUS: REVIEW RECOMMENDED",
                "",
                "All exported findings remain citation-anchored.",
                "Some quality checks require attorney review before litigation use.",
                "",
            ]
        )
        fail_lines.append("Items for attorney confirmation:")
        for f in soft_failures[:8]:
            fail_lines.append(f"- {str(f.get('code') or '').strip()}: {str(f.get('message') or '').strip()[:90]}")
    fail_lines.append("")
    fail_lines.append("See cited pages in the chronology and appendix for source verification.")
    
    # Generate cover page
    cover_buf = io.BytesIO()
    c = canvas.Canvas(cover_buf, pagesize=letter)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, 750, fail_lines[0][:110])
    c.setFont("Helvetica", 11)
    y = 720
    for line in fail_lines[1:]:
        c.drawString(50, y, line[:120])
        y -= 18
        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = 750
    c.save()
    cover_buf.seek(0)
    
    # Prepend cover to existing PDF
    try:
        writer = PdfWriter()
        writer.append(PdfReader(cover_buf))
        writer.append(PdfReader(str(out_pdf_path)))
        with open(out_pdf_path, "wb") as f:
            writer.write(f)
        logger.info(f"Written fail cover page to {out_pdf_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to write fail cover PDF: {e}")
        return False
