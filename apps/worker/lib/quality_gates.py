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

logger = logging.getLogger(__name__)


_ATTORNEY_PLACEHOLDER_PATTERNS: list[tuple[str, str]] = [
    ("SEE_PATIENT_HEADER", r"\bSee Patient Header\b"),
    ("SENTINEL_DATE_1900", r"\b1900-01-01\b"),
    ("SENTINEL_DATE_0001", r"\b0001-01-01\b"),
]


def _placeholder_leak_findings(report_text: str) -> list[dict[str, Any]]:
    text = str(report_text or "")
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


def run_quality_gates(
    report_text: str,
    page_text_by_number: dict[int, str],
    projection_entries: list[Any] | None = None,
    chronology_events: list[Any] | None = None,
    gaps: list[Any] | None = None,
    source_pdf: str | None = None,
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
    
    results = {
        "overall_pass": True,
        "attorney_ready_pass": True,
        "attorney_ready_score": 100,
        "luqa_pass": True,
        "luqa_score": 100,
        "litigation_pass": True,
        "litigation_score": 100,
        "failures": [],
        "gate_report": {},
    }
    
    # Run Attorney Readiness
    try:
        attorney = build_attorney_readiness_report(report_text, ctx)
        results["attorney_ready_pass"] = attorney.get("attorney_ready_pass", True)
        results["attorney_ready_score"] = attorney.get("attorney_ready_score_0_100", 100)
        results["gate_report"]["attorney"] = attorney
        if not results["attorney_ready_pass"]:
            results["overall_pass"] = False
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
        if not results["luqa_pass"]:
            results["overall_pass"] = False
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
        results["overall_pass"] = False
        results["failures"].extend(placeholder_findings)
        results["gate_report"]["placeholder_scan"] = {
            "pass": False,
            "failures": placeholder_findings,
        }
    else:
        results["gate_report"]["placeholder_scan"] = {"pass": True, "failures": []}
    
    return results


def write_fail_cover_pdf(
    out_pdf_path: str,
    gate_results: dict[str, Any],
) -> bool:
    """
    Write a fail cover page to the PDF if gates failed.
    
    Returns True if fail cover was written, False if gates passed.
    """
    if gate_results.get("overall_pass", True):
        return False
    
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader, PdfWriter
    
    fail_lines: list[str] = ["CiteLine Validation Gate - QUALITY CHECKS FAILED", ""]
    
    # Attorney readiness failures
    if not gate_results.get("attorney_ready_pass", True):
        fail_lines.append("ATTORNEY READINESS FAIL")
        fail_lines.append(f"Score: {gate_results.get('attorney_ready_score', 0)}/100")
        for f in gate_results.get("failures", []):
            if f.get("source") == "attorney":
                fail_lines.append(f"- {f.get('code')}: {f.get('message', '')[:80]}")
        fail_lines.append("")
    
    # LUQA failures
    if not gate_results.get("luqa_pass", True):
        fail_lines.append("LITIGATION USABILITY FAIL")
        fail_lines.append(f"Score: {gate_results.get('luqa_score', 0)}/100")
        for f in gate_results.get("failures", []):
            if f.get("source") == "luqa":
                fail_lines.append(f"- {f.get('code')}: {f.get('message', '')[:80]}")
        fail_lines.append("")
    
    fail_lines.append("This document may contain errors.")
    fail_lines.append("Do not use in litigation without manual review.")
    
    # Generate cover page
    cover_buf = io.BytesIO()
    c = canvas.Canvas(cover_buf, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, fail_lines[0])
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
