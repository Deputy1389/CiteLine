from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date
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
from apps.worker.steps.step03b_patient_partitions import (
    assign_patient_scope_to_events,
    build_patient_partitions,
    enforce_event_patient_scope,
    validate_patient_scope_invariants,
)
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
from apps.worker.steps.events.event_weighting import annotate_event_weights
from apps.worker.steps.step11_gaps import detect_gaps
from apps.worker.steps.step12_export import (
    _enrich_projection_procedure_entries,
    _ensure_mri_bucket_entry,
    _ensure_ortho_bucket_entry,
    _ensure_procedure_bucket_entry,
    _normalize_projection_patient_labels,
    render_exports,
    render_patient_chronology_reports,
)
from apps.worker.steps.step15_missing_records import detect_missing_records
from apps.worker.lib.provider_normalize import normalize_provider_entities
from apps.worker.lib.claim_ledger_lite import build_claim_edges, select_top_claim_rows
from apps.worker.lib.causation_ladder import build_causation_ladders
from apps.worker.steps.case_collapse import (
    build_case_collapse_candidates,
    build_defense_attack_paths,
    build_objection_profiles,
    build_upgrade_recommendations,
    quote_lock,
)
from apps.worker.steps.litigation import (
    build_comparative_pattern_snapshot,
    build_contradiction_matrix,
    build_narrative_duality,
)
from apps.worker.lib.noise_filter import is_noise_span
from apps.worker.steps.step12a_narrative_synthesis import synthesize_narrative
from apps.worker.project.chronology import build_chronology_projection, infer_page_patient_labels
from scripts.litigation_qa import build_litigation_checklist, write_litigation_checklist
from packages.shared.models import CaseInfo, ClaimEdge, EvidenceGraph, Gap, LitigationExtensions, RunConfig, SourceDocument
from packages.shared.storage import get_artifact_dir
from apps.worker.lib.artifacts_writer import write_artifact_json
from apps.worker.lib.artifacts_writer import safe_copy, validate_artifacts_exist
from apps.worker.lib.luqa import build_luqa_report
from apps.worker.lib.attorney_readiness import build_attorney_readiness_report


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


def _build_litigation_extensions(claim_rows: list[dict] | list[ClaimEdge]) -> dict:
    anchored_rows = [r for r in claim_rows if (r.get("citations") or [])]
    collapse_candidates = build_case_collapse_candidates(anchored_rows)
    attack_paths = build_defense_attack_paths(collapse_candidates, limit=6)
    objection_profiles = build_objection_profiles(anchored_rows, limit=24)
    upgrade_recs = build_upgrade_recommendations(collapse_candidates, limit=8)
    locked_quotes: list[dict] = []
    for row in select_top_claim_rows(anchored_rows, limit=12):
        q = quote_lock(str(row.get("assertion") or ""))
        if not q:
            continue
        locked_quotes.append(
            {
                "id": str(row.get("id") or ""),
                "date": str(row.get("date") or "unknown"),
                "claim_type": str(row.get("claim_type") or ""),
                "quote": q,
                "citation": str(row.get("citation") or ""),
                "event_id": str(row.get("event_id") or ""),
            }
        )
    payload = {
        "claim_rows": anchored_rows,
        "causation_chains": build_causation_ladders(anchored_rows),
        "citation_fidelity": {
            "claim_rows_total": len(claim_rows),
            "claim_rows_anchored": len(anchored_rows),
            "claim_row_anchor_ratio": round((len(anchored_rows) / len(claim_rows)), 4) if claim_rows else 1.0,
        },
        "case_collapse_candidates": collapse_candidates,
        "defense_attack_paths": attack_paths,
        "objection_profiles": objection_profiles,
        "evidence_upgrade_recommendations": upgrade_recs,
        "quote_lock_rows": locked_quotes,
        "contradiction_matrix": build_contradiction_matrix(anchored_rows),
        "narrative_duality": build_narrative_duality(anchored_rows),
        "comparative_pattern_engine": build_comparative_pattern_snapshot(anchored_rows),
    }
    return LitigationExtensions.model_validate(payload).model_dump(mode="json")


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
    patient_partitions_payload, page_to_patient_scope = build_patient_partitions(pages)

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
    weight_summary = annotate_event_weights(all_events)
    assign_patient_scope_to_events(all_events, page_to_patient_scope)
    enforce_event_patient_scope(all_events, all_citations, page_to_patient_scope)
    filtered_for_gaps = [e.model_copy(deep=True) for e in all_events]
    filtered_for_gaps, gaps, _ = detect_gaps(filtered_for_gaps, config)
    chronology_events = improve_legal_usability([e.model_copy(deep=True) for e in all_events])
    # Deterministic noise quarantine for downstream rendering/evidence graph artifacts.
    for evt in chronology_events:
        clean_facts = []
        for fact in evt.facts:
            txt = (fact.text or "").strip()
            if not txt:
                continue
            if is_noise_span(txt):
                continue
            clean_facts.append(fact)
        evt.facts = clean_facts
    page_text_by_number = {p.page_number: (p.text or "") for p in pages}
    page_patient_labels = infer_page_patient_labels(page_text_by_number)
    projection_debug: list[dict] = []
    projection = build_chronology_projection(
        chronology_events,
        providers,
        page_map=None,
        page_patient_labels=page_patient_labels,
        page_text_by_number=page_text_by_number,
        debug_sink=projection_debug,
    )
    non_unknown_labels = sorted(
        {
            (e.patient_label or "").strip()
            for e in projection.entries
            if (e.patient_label or "").strip() and (e.patient_label or "").strip().lower() != "unknown patient"
        }
    )
    projection_label_fallback = non_unknown_labels[0] if non_unknown_labels else "See Patient Header"
    normalized_projection_entries = []
    for e in projection.entries:
        if (e.patient_label or "").strip().lower() == "unknown patient":
            normalized_projection_entries.append(e.model_copy(update={"patient_label": projection_label_fallback}))
        else:
            normalized_projection_entries.append(e)

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

    graph = EvidenceGraph(pages=pages, documents=docs, providers=providers, events=chronology_events, citations=all_citations)
    claim_edges = build_claim_edges([], raw_events=chronology_events)
    graph.extensions.update(_build_litigation_extensions(claim_edges))
    provider_norm = normalize_provider_entities(graph)
    missing_payload = detect_missing_records(graph, provider_norm)
    artifact_dir = get_artifact_dir(run_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    evidence_graph_payload = graph.model_dump(mode="json")
    write_artifact_json("evidence_graph.json", evidence_graph_payload, artifact_dir)
    write_artifact_json("patient_partitions.json", patient_partitions_payload, artifact_dir)
    write_artifact_json("missing_records.json", missing_payload, artifact_dir)
    render_gaps: list[Gap] = []
    for row in (missing_payload.get("gaps") or []):
        try:
            s = row.get("start_date")
            e = row.get("end_date")
            if isinstance(s, str):
                s = date.fromisoformat(s)
            if isinstance(e, str):
                e = date.fromisoformat(e)
            evidence = row.get("evidence") or {}
            related_ids = [str(x) for x in (row.get("related_event_ids") or []) if x]
            if not related_ids:
                if evidence.get("last_event_id"):
                    related_ids.append(str(evidence.get("last_event_id")))
                if evidence.get("next_event_id"):
                    related_ids.append(str(evidence.get("next_event_id")))
            render_gaps.append(
                Gap(
                    gap_id=str(row.get("gap_id") or f"mr_gap_{len(render_gaps)+1}"),
                    start_date=s,
                    end_date=e,
                    duration_days=int(row.get("gap_days") or row.get("duration_days") or 0),
                    threshold_days=int(row.get("threshold_days") or 60),
                    confidence=int(row.get("confidence") or 80),
                    related_event_ids=related_ids,
                )
            )
        except Exception:
            continue

    chronology = render_exports(
        run_id=run_id,
        matter_title="Sample 172 Chronology Eval",
        events=chronology_events,
        gaps=render_gaps,
        providers=providers,
        page_map=page_map,
        case_info=case_info,
        all_citations=all_citations,
        narrative_synthesis=narrative,
        page_text_by_number=page_text_by_number,
        evidence_graph_payload=evidence_graph_payload,
        patient_partitions_payload=patient_partitions_payload,
        missing_records_payload=missing_payload,
    )
    patient_manifest_ref = render_patient_chronology_reports(
        run_id=run_id,
        matter_title="Sample 172 Chronology Eval",
        events=chronology_events,
        providers=providers,
        page_map=page_map,
        page_text_by_number=page_text_by_number,
    )

    # Keep QA context projection aligned with export-time enrichment/backfill logic.
    projection_for_ctx = projection.model_copy(update={"entries": normalized_projection_entries})
    projection_for_ctx = _enrich_projection_procedure_entries(
        projection_for_ctx,
        page_text_by_number=page_text_by_number,
        page_map=page_map,
    )
    projection_for_ctx = _ensure_mri_bucket_entry(
        projection_for_ctx,
        page_text_by_number=page_text_by_number,
        page_map=page_map,
    )
    projection_for_ctx = _ensure_procedure_bucket_entry(
        projection_for_ctx,
        page_text_by_number=page_text_by_number,
        page_map=page_map,
    )
    projection_for_ctx = _ensure_ortho_bucket_entry(
        projection_for_ctx,
        page_text_by_number=page_text_by_number,
        page_map=page_map,
        raw_events=chronology_events,
    )
    projection_for_ctx = _normalize_projection_patient_labels(projection_for_ctx)

    patient_scope_violations = validate_patient_scope_invariants(all_events, all_citations, page_to_patient_scope)
    pdf_path = Path(chronology.exports.pdf.uri)
    return pdf_path, {
        "events": chronology_events,
        "projection_entries": projection_for_ctx.entries,
        "projection_debug": projection_debug,
        "patient_manifest_ref": patient_manifest_ref.uri if patient_manifest_ref else None,
        "missing_records_payload": missing_payload,
        "patient_partitions_payload": patient_partitions_payload,
        "patient_scope_violations": patient_scope_violations,
        "gaps_count": len(gaps),
        "event_weighting": weight_summary,
        "source_pages": len(pages),
        "page_text_by_number": page_text_by_number,
        "artifact_manifest": {
            "evidence_graph.json": str((artifact_dir / "evidence_graph.json").resolve()),
            "patient_partitions.json": str((artifact_dir / "patient_partitions.json").resolve()),
            "missing_records.json": str((artifact_dir / "missing_records.json").resolve()),
            "selection_debug.json": str((artifact_dir / "selection_debug.json").resolve()),
            "claim_guard_report.json": str((artifact_dir / "claim_guard_report.json").resolve()),
        },
    }


def _has_old_dates(report_text: str) -> bool:
    if "1900-01-01" in report_text:
        return True
    for year, _, _ in DATE_RE.findall(report_text):
        if int(year) < 1901:
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
    projection_patient_label_count = len(
        {
            e.patient_label
            for e in ctx.get("projection_entries", [])
            if getattr(e, "patient_label", "Unknown Patient") != "Unknown Patient"
        }
    )
    source_pages = int(ctx.get("source_pages", 0) or 0)
    if projection_patient_label_count <= 1:
        if source_pages >= 250:
            timeline_limit = 220
        elif source_pages >= 150:
            timeline_limit = 140
        elif source_pages >= 80:
            timeline_limit = 110
        else:
            timeline_limit = 80
    else:
        timeline_limit = min(400, projection_patient_label_count * 15)
    provider_misassignment_count = 0
    for entry in ctx.get("projection_entries", []):
        provider = (entry.provider_display or "").lower()
        event_type = (entry.event_type_display or "").lower()
        if "erick brick md radiology" in provider and event_type != "imaging study":
            provider_misassignment_count += 1
    patient_scope_violation_count = len(ctx.get("patient_scope_violations", []))

    surgery_count = sum(
        1
        for entry in ctx.get("projection_entries", [])
        if "procedure" in (getattr(entry, "event_type_display", "") or "").lower()
    )
    surgery_events_count = 0
    for event in ctx.get("events", []):
        if event.event_type.value == "procedure" and surgery_classifier_guard(event):
            surgery_events_count += 1
    if total_surgeries_field is None or total_surgeries_field <= 0:
        total_surgeries_field = max(surgery_count, surgery_events_count)
    injury_list = sorted(set(injury_canonicalization(report_text)))
    missing_records_section_present = "missing record" in text_lower

    empty_surgery_entries = 0
    for event in ctx["events"]:
        facts_blob = " ".join(f.text for f in event.facts if f.text).lower()
        surgery_like = event.event_type.value == "procedure" or any(
            token in facts_blob for token in ("surgery", "operative", "orif", "debrid", "repair", "hardware removal")
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
            timeline_entry_count >= timeline_limit,
            provider_misassignment_count > 0,
            patient_scope_violation_count > 0,
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
        "projection_patient_label_count": projection_patient_label_count,
        "timeline_limit": timeline_limit,
        "source_pages": source_pages,
        "provider_misassignment_count": provider_misassignment_count,
        "patient_scope_violation_count": patient_scope_violation_count,
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
    artifact_dir = get_artifact_dir(run_id)

    out_pdf = eval_dir / "output.pdf"
    shutil.copyfile(pdf_path, out_pdf)
    manifest = dict(ctx.get("artifact_manifest") or {})
    for name in [
        "evidence_graph.json",
        "patient_partitions.json",
        "missing_records.json",
        "selection_debug.json",
        "claim_guard_report.json",
    ]:
        src = Path(manifest.get(name) or (artifact_dir / name))
        copied = safe_copy(src, eval_dir, name) if src.exists() else None
        manifest[name] = str(copied.resolve()) if copied else None
    seed_semqa = {"run_id": run_id, "qa_pass": None}
    semqa_path = write_artifact_json("semqa_debug.json", seed_semqa, eval_dir)
    write_artifact_json("semqa_debug.json", seed_semqa, artifact_dir)
    manifest["semqa_debug.json"] = str(semqa_path.resolve())
    ctx["artifact_manifest"] = manifest
    report_text = extract_pdf_text(out_pdf)
    scorecard = score_report(report_text, ctx)
    checklist = build_litigation_checklist(
        run_id=run_id,
        source_pdf=str(sample_pdf),
        report_text=report_text,
        ctx=ctx,
        chronology_pdf_path=out_pdf,
    )
    write_litigation_checklist(eval_dir / "qa_litigation_checklist.json", checklist)
    luqa = build_luqa_report(report_text, ctx)
    luqa_path = write_artifact_json("luqa_report.json", luqa, eval_dir)
    write_artifact_json("luqa_report.json", luqa, artifact_dir)
    manifest["luqa_report.json"] = str(luqa_path.resolve())
    attorney = build_attorney_readiness_report(report_text, ctx)
    attorney_path = write_artifact_json("attorney_readiness_report.json", attorney, eval_dir)
    write_artifact_json("attorney_readiness_report.json", attorney, artifact_dir)
    manifest["attorney_readiness_report.json"] = str(attorney_path.resolve())
    ctx["artifact_manifest"] = manifest
    semqa = {
        "run_id": run_id,
        "qa_pass": bool(checklist.get("pass")),
        "quality_gates": checklist.get("quality_gates", {}),
        "metrics": checklist.get("metrics", {}),
    }
    write_artifact_json("semqa_debug.json", semqa, eval_dir)
    write_artifact_json("semqa_debug.json", semqa, artifact_dir)
    qa_score = int(checklist.get("score_0_100", 0) or 0)
    scorecard["qa_litigation_pass"] = bool(checklist["pass"]) or qa_score >= 80
    scorecard["qa_score"] = qa_score
    scorecard["luqa_pass"] = bool(luqa.get("luqa_pass"))
    scorecard["luqa_score"] = int(luqa.get("luqa_score_0_100", 0) or 0)
    scorecard["luqa_failures_count"] = len(luqa.get("failures") or [])
    scorecard["attorney_ready_pass"] = bool(attorney.get("attorney_ready_pass"))
    scorecard["attorney_ready_score"] = int(attorney.get("attorney_ready_score_0_100", 0) or 0)
    scorecard["attorney_ready_failures_count"] = len(attorney.get("failures") or [])
    scorecard["score_0_100"] = int(checklist.get("score_0_100", scorecard.get("score_0_100", 0)) or 0)
    scorecard["overall_pass"] = bool(scorecard["qa_litigation_pass"]) and bool(luqa.get("luqa_pass")) and bool(attorney.get("attorney_ready_pass"))

    debug_trace_written = False
    if debug_trace:
        trace = {
            "run_id": run_id,
            "events_count": len(ctx["events"]),
            "projection_entry_count": len(ctx.get("projection_entries", [])),
            "projection_excluded": ctx.get("projection_debug", []),
            "missing_records": ctx["missing_records_payload"],
            "patient_partitions": ctx.get("patient_partitions_payload", {}),
            "patient_scope_violations": ctx.get("patient_scope_violations", []),
        }
        trace_path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
        debug_trace_written = True

    scorecard["debug_trace_written"] = debug_trace_written
    artifacts_ok, missing = validate_artifacts_exist({k: v for k, v in manifest.items()})
    scorecard["artifact_manifest_ok"] = artifacts_ok
    scorecard["artifact_manifest_missing"] = missing

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
