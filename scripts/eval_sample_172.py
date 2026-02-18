from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.worker.pipeline_artifacts import build_page_map
from apps.worker.steps.events.legal_usability import improve_legal_usability
from apps.worker.steps.events.report_quality import (
    PAGE_ARTIFACT_RE,
    NUM_TWO_ARTIFACT_RE,
    UUID_RE,
    injury_canonicalization,
    procedure_canonicalization,
    surgery_classifier_guard,
)
from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step02_text_acquire import acquire_text
from apps.worker.steps.step03_classify import classify_pages
from apps.worker.steps.step03a_demographics import extract_demographics
from apps.worker.steps.step04_segment import segment_documents
from apps.worker.steps.step05_provider import detect_providers
from apps.worker.steps.step06_dates import extract_dates_for_pages
from apps.worker.steps.step07_events import (
    extract_billing_events,
    extract_clinical_events,
    extract_discharge_events,
    extract_imaging_events,
    extract_lab_events,
    extract_operative_events,
    extract_pt_events,
)
from apps.worker.steps.step08_citations import post_process_citations
from apps.worker.steps.step09_dedup import deduplicate_events
from apps.worker.steps.step10_confidence import apply_confidence_scoring
from apps.worker.steps.step11_gaps import detect_gaps
from apps.worker.steps.step12_export import render_exports
from apps.worker.steps.step15_missing_records import detect_missing_records
from apps.worker.lib.provider_normalize import normalize_provider_entities
from apps.worker.steps.step12a_narrative_synthesis import synthesize_narrative
from apps.worker.project.chronology import build_chronology_projection, infer_page_patient_labels
from packages.shared.models import CaseInfo, EvidenceGraph, RunConfig, SourceDocument
from packages.shared.storage import get_artifact_dir


FORBIDDEN_STRINGS = [
    "records of harry potter",
    "pdf_page",
    "pdf page",
    "chapman",
    "review of systems",
    "printed page",
]
DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
UUID_PROVIDER_RE = UUID_RE


def locate_sample_pdf() -> Path:
    candidates = [
        ROOT / "sample-medical-chronology172.pdf",
        ROOT / "testdata" / "sample-medical-chronology172.pdf",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "sample-medical-chronology172.pdf not found. Expected at "
        "C:/CiteLine/sample-medical-chronology172.pdf or C:/CiteLine/testdata/sample-medical-chronology172.pdf"
    )


def extract_pdf_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    return "\n".join((doc[i].get_text("text") or "") for i in range(doc.page_count))


def run_sample_pipeline(sample_pdf: Path, run_id: str) -> tuple[Path, dict[str, Any]]:
    config = RunConfig(max_pages=1000)
    pages, _ = split_pages(str(sample_pdf), sample_pdf.name, page_offset=0, max_pages=config.max_pages)
    pages, _, _ = acquire_text(pages, str(sample_pdf))
    pages, _ = classify_pages(pages)
    patient, _ = extract_demographics(pages)

    docs, _ = segment_documents(pages, sample_pdf.name)
    providers, page_provider_map, _ = detect_providers(pages, docs)
    dates = extract_dates_for_pages(pages)

    all_events = []
    all_citations = []
    all_skipped = []
    for extractor in (
        extract_clinical_events,
        extract_imaging_events,
        extract_pt_events,
        extract_billing_events,
        extract_lab_events,
        extract_discharge_events,
        extract_operative_events,
    ):
        if extractor is extract_pt_events:
            events, citations, _, skipped = extractor(pages, dates, providers, config, page_provider_map)
        else:
            events, citations, _, skipped = extractor(pages, dates, providers, page_provider_map)
        all_events.extend(events)
        all_citations.extend(citations)
        all_skipped.extend(skipped)

    all_citations, _ = post_process_citations(all_citations)
    all_events, _ = deduplicate_events(all_events)
    all_events, _ = apply_confidence_scoring(all_events, config)
    filtered_for_gaps = [e.model_copy(deep=True) for e in all_events]
    filtered_for_gaps, gaps, _ = detect_gaps(filtered_for_gaps, config)
    chronology_events = improve_legal_usability([e.model_copy(deep=True) for e in all_events])
    page_text_by_number = {p.page_number: (p.text or "") for p in pages}
    page_patient_labels = infer_page_patient_labels(page_text_by_number)
    projection_debug: list[dict] = []
    projection = build_chronology_projection(
        chronology_events,
        providers,
        page_map=None,
        page_patient_labels=page_patient_labels,
        debug_sink=projection_debug,
    )

    page_map = build_page_map(
        all_pages=pages,
        source_documents=[
            SourceDocument(
                document_id=sample_pdf.name,
                filename=sample_pdf.name,
                mime_type="application/pdf",
                sha256="0" * 64,
                bytes=sample_pdf.stat().st_size,
            )
        ],
    )
    case_info = CaseInfo(
        case_id="sample-172",
        firm_id="eval",
        title="Sample 172",
        patient=patient,
    )
    narrative = synthesize_narrative(chronology_events, providers, all_citations, case_info)

    chronology = render_exports(
        run_id=run_id,
        matter_title="Sample 172 Chronology Eval",
        events=chronology_events,
        gaps=gaps,
        providers=providers,
        page_map=page_map,
        case_info=case_info,
        all_citations=all_citations,
        narrative_synthesis=narrative,
        page_text_by_number=page_text_by_number,
    )

    graph = EvidenceGraph(pages=pages, documents=docs, providers=providers, events=chronology_events, citations=all_citations)
    provider_norm = normalize_provider_entities(graph)
    missing_payload = detect_missing_records(graph, provider_norm)
    pdf_path = Path(chronology.exports.pdf.uri)
    return pdf_path, {
        "events": chronology_events,
        "projection_entries": projection.entries,
        "projection_debug": projection_debug,
        "missing_records_payload": missing_payload,
        "gaps_count": len(gaps),
    }


def _has_old_dates(report_text: str) -> bool:
    if "1900-01-01" in report_text:
        return True
    for year, _, _ in DATE_RE.findall(report_text):
        if int(year) < 1970:
            return True
    return False


def score_report(report_text: str, ctx: dict[str, Any]) -> dict[str, Any]:
    text_lower = report_text.lower()
    forbidden_found = [s for s in FORBIDDEN_STRINGS if s in text_lower]
    has_uuid_provider_ids = bool(UUID_PROVIDER_RE.search(report_text))
    has_placeholder_dates = _has_old_dates(report_text)

    total_surgeries_field = None
    total_surgeries_match = re.search(r"total surgeries\s*[:\-]\s*(\d+)", report_text, re.IGNORECASE)
    if total_surgeries_match:
        total_surgeries_field = int(total_surgeries_match.group(1))

    has_atom_dump_marker = bool(
        re.search(
            r"(chronology|chronological medical timeline)\s+pt visit\s+provider:",
            text_lower,
            re.IGNORECASE,
        )
    )
    has_date_not_documented_pt_visit = bool(
        re.search(r"date not documented\s*-\s*pt visit", text_lower, re.IGNORECASE)
    )
    has_provider_lines_in_timeline = bool(
        re.search(r"chronological medical timeline[\s\S]{0,1200}\bprovider:", text_lower, re.IGNORECASE)
    )

    has_raw_fragment_dump = (
        ("clinical timeline" in text_lower)
        or has_atom_dump_marker
        or has_date_not_documented_pt_visit
        or bool(PAGE_ARTIFACT_RE.search(report_text))
        or bool(NUM_TWO_ARTIFACT_RE.search(report_text))
    )
    timeline_entry_count = len(ctx.get("projection_entries", []))
    provider_misassignment_count = 0
    for entry in ctx.get("projection_entries", []):
        provider = (entry.provider_display or "").lower()
        event_type = (entry.event_type_display or "").lower()
        if "erick brick md radiology" in provider and event_type != "imaging study":
            provider_misassignment_count += 1

    surgery_count = len(re.findall(r"\b(surgery|operative|orif|debridement|hardware removal|rotator cuff repair)\b", text_lower))
    injury_list = sorted(set(injury_canonicalization(report_text)))
    missing_records_section_present = "missing record" in text_lower

    empty_surgery_entries = 0
    for event in ctx["events"]:
        facts_blob = " ".join(f.text for f in event.facts if f.text).lower()
        surgery_like = event.event_type.value == "procedure" or any(
            token in facts_blob for token in ("surgery", "procedure", "operative", "orif", "debrid", "repair")
        )
        if not surgery_like:
            continue
        if not surgery_classifier_guard(event):
            # Renderer excludes this event, so it does not produce a client-facing surgery entry.
            continue
        if len(procedure_canonicalization(facts_blob)) == 0:
            empty_surgery_entries += 1

    hard_fail = any(
        [
            bool(forbidden_found),
            has_uuid_provider_ids,
            has_placeholder_dates,
            has_raw_fragment_dump,
            has_provider_lines_in_timeline,
            timeline_entry_count >= 80,
            provider_misassignment_count > 0,
            empty_surgery_entries > 0,
            bool(PAGE_ARTIFACT_RE.search(report_text)),
            bool(NUM_TWO_ARTIFACT_RE.search(report_text)),
        ]
    )

    return {
        "forbidden_strings_found": forbidden_found,
        "has_placeholder_dates": has_placeholder_dates,
        "has_uuid_provider_ids": has_uuid_provider_ids,
        "has_raw_fragment_dump": has_raw_fragment_dump,
        "surgery_count": surgery_count,
        "injury_list": injury_list,
        "missing_records_section_present": missing_records_section_present,
        "empty_surgery_entries": empty_surgery_entries,
        "total_surgeries_field": total_surgeries_field,
        "has_atom_dump_marker": has_atom_dump_marker,
        "has_date_not_documented_pt_visit": has_date_not_documented_pt_visit,
        "has_provider_lines_in_timeline": has_provider_lines_in_timeline,
        "timeline_entry_count": timeline_entry_count,
        "provider_misassignment_count": provider_misassignment_count,
        "overall_pass": not hard_fail,
    }


def evaluate_sample_172(debug_trace: bool = False) -> dict[str, Any]:
    sample_pdf = locate_sample_pdf()
    eval_dir = ROOT / "data" / "evals" / "sample_172"
    eval_dir.mkdir(parents=True, exist_ok=True)
    trace_path = eval_dir / "evidence_trace.json"
    if not debug_trace and trace_path.exists():
        trace_path.unlink()

    run_id = f"eval-sample-172-{uuid4().hex[:8]}"
    pdf_path, ctx = run_sample_pipeline(sample_pdf, run_id)

    out_pdf = eval_dir / "output.pdf"
    shutil.copyfile(pdf_path, out_pdf)
    report_text = extract_pdf_text(out_pdf)
    scorecard = score_report(report_text, ctx)

    debug_trace_written = False
    if debug_trace:
        trace = {
            "run_id": run_id,
            "events_count": len(ctx["events"]),
            "projection_entry_count": len(ctx.get("projection_entries", [])),
            "projection_excluded": ctx.get("projection_debug", []),
            "missing_records": ctx["missing_records_payload"],
        }
        trace_path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
        debug_trace_written = True

    scorecard["debug_trace_written"] = debug_trace_written

    scorecard_path = eval_dir / "scorecard.json"
    scorecard_path.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
    return scorecard


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic litigation-grade evaluation for sample-medical-chronology172.pdf.")
    parser.add_argument("--debug-trace", action="store_true", help="Write evidence_trace.json (default off).")
    args = parser.parse_args()

    scorecard = evaluate_sample_172(debug_trace=args.debug_trace)
    print(json.dumps(scorecard, indent=2))
    return 0 if scorecard["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
