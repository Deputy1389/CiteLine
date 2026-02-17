from __future__ import annotations

from pathlib import Path

import fitz

from apps.worker.steps.step18_paralegal_chronology import (
    build_paralegal_chronology_payload,
    generate_paralegal_chronology_md,
)
from apps.worker.tools.paralegal_chronology_eval import evaluate_paralegal_chronology
from packages.shared.models import EvidenceGraph, Page


def _sample_pdf_path() -> Path:
    return Path("testdata/sample-medical-chronology172.pdf")


def _build_graph_from_sample_pdf() -> EvidenceGraph:
    pdf_path = _sample_pdf_path()
    doc = fitz.open(str(pdf_path))
    pages: list[Page] = []
    for idx in range(doc.page_count):
        pages.append(
            Page(
                page_id=f"sample-p{idx + 1}",
                source_document_id="sample-medical-chronology172.pdf",
                page_number=idx + 1,
                text=doc[idx].get_text("text") or "",
                text_source="embedded",
            )
        )
    return EvidenceGraph(pages=pages)


def test_quality_gate_passes_on_sample_internal_chronology():
    graph = _build_graph_from_sample_pdf()
    page_map = {p.page_number: ("sample-medical-chronology172.pdf", p.page_number) for p in graph.pages}
    payload = build_paralegal_chronology_payload(
        evidence_graph=graph,
        events_for_chronology=[],
        providers=[],
        page_map=page_map,
    )
    md_text = generate_paralegal_chronology_md(payload).decode("utf-8")

    report = evaluate_paralegal_chronology(md_text, _sample_pdf_path())
    assert report["passed"] is True
    assert report["checks"]["required_dates_and_milestones"] is True
    assert report["checks"]["includes_last_follow_up_01_21_2014"] is True
    assert report["checks"]["density_threshold_met"] is True
    assert report["score"] == 100


def test_quality_gate_fails_when_required_milestones_missing():
    md_text = """# Paralegal Chronology

## 04/29/2013
- Injury visit noted.

## 01/21/2014
- Follow-up visit.
"""
    report = evaluate_paralegal_chronology(md_text, _sample_pdf_path())
    assert report["passed"] is False
    assert report["checks"]["required_dates_and_milestones"] is False
