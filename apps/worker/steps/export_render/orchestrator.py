"""
Orchestrator for export rendering.

Coordinates PDF, CSV, DOCX, and Markdown export generation.
Extracted from step12_export.py during refactor - behavior preserved exactly.
"""
from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from packages.shared.models import ArtifactRef, ChronologyExports, ChronologyOutput
from packages.shared.storage import save_artifact
from apps.worker.project.chronology import build_chronology_projection, infer_page_patient_labels
from apps.worker.project.models import ChronologyProjection
from apps.worker.lib.claim_guard import apply_claim_guard_to_narrative
from apps.worker.lib.claim_ledger_lite import build_claim_ledger_lite
from apps.worker.steps.case_collapse import build_case_collapse_candidates
from apps.worker.steps.export_render.projection_pipeline import (
    build_selection_debug_payload,
    prepare_projection_bundle,
)
from apps.worker.steps.export_render.timeline_pdf import generate_pdf_from_projection, generate_executive_summary
from apps.worker.steps.export_render.csv_render import generate_csv_from_projection
from apps.worker.steps.export_render.docx_render import generate_docx
from apps.worker.steps.export_render.markdown_render import build_markdown_bytes
from apps.worker.steps.export_render.common import (
    _clean_narrative_text,
    _slugify,
)
from apps.worker.steps.export_render.extraction_utils import _repair_case_summary_narrative
from apps.worker.steps.export_render.orchestrator_utils import (
    _normalize_projection_patient_labels,
    _merge_projection_entries_same_day,
    _compute_care_window_from_projection,
)
from apps.worker.steps.export_render.projection_enrichment import (
    _enrich_projection_procedure_entries,
    _ensure_mri_bucket_entry,
    _ensure_procedure_bucket_entry,
    _ensure_ortho_bucket_entry,
)

if TYPE_CHECKING:
    from packages.shared.models import CaseInfo, Citation, Event, Gap, Provider


def render_exports(
    run_id: str,
    matter_title: str,
    events: list[Event],
    gaps: list[Gap],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
    case_info: CaseInfo | None = None,
    all_citations: list[Citation] | None = None,
    narrative_synthesis: str | None = None,
    page_text_by_number: dict[int, str] | None = None,
    evidence_graph_payload: dict | None = None,
    patient_partitions_payload: dict | None = None,
    missing_records_payload: dict | None = None,
) -> ChronologyOutput:
    """
    Render all export formats, save to disk, and return ChronologyOutput.
    """
    provider_none_count = sum(1 for e in events if not e.provider_id or e.provider_id == "unknown")
    print(f"chronology_generation_input: {len(events)} events (provider_none_or_unknown={provider_none_count})")
    
    projection_bundle = prepare_projection_bundle(
        events=events,
        providers=providers,
        page_map=page_map,
        page_text_by_number=page_text_by_number,
        narrative_synthesis=narrative_synthesis,
        missing_records_payload=missing_records_payload,
        build_chronology_projection=build_chronology_projection,
        infer_page_patient_labels=infer_page_patient_labels,
        enrich_projection_procedure_entries=_enrich_projection_procedure_entries,
        ensure_mri_bucket_entry=_ensure_mri_bucket_entry,
        ensure_procedure_bucket_entry=_ensure_procedure_bucket_entry,
        ensure_ortho_bucket_entry=_ensure_ortho_bucket_entry,
        normalize_projection_patient_labels=_normalize_projection_patient_labels,
        merge_projection_entries_same_day=_merge_projection_entries_same_day,
        compute_care_window_from_projection=_compute_care_window_from_projection,
        apply_claim_guard_to_narrative=apply_claim_guard_to_narrative,
        repair_case_summary_narrative=_repair_case_summary_narrative,
    )
    projection = projection_bundle["projection"]
    appendix_projection = projection_bundle["appendix_projection"]
    care_window = projection_bundle["care_window"]
    narrative_synthesis = projection_bundle["narrative_synthesis"]
    claim_guard_report = projection_bundle["claim_guard_report"]
    projection_debug = projection_bundle["projection_debug"]
    selection_meta = projection_bundle["selection_meta"]
    exported_ids = [entry.event_id for entry in projection.entries]
    
    selection_debug_payload = build_selection_debug_payload(
        selection_meta=selection_meta,
        events=events,
        projection_debug=projection_debug,
    )
    save_artifact(run_id, "selection_debug.json", json.dumps(selection_debug_payload, indent=2).encode("utf-8"))
    save_artifact(run_id, "claim_guard_report.json", json.dumps(claim_guard_report, indent=2).encode("utf-8"))
    
    debug_artifacts = str(os.getenv("DEBUG_ARTIFACTS", "false")).strip().lower() in {"1", "true", "yes", "on"}
    if debug_artifacts:
        claim_rows_debug = build_claim_ledger_lite(projection.entries, raw_events=events)
        collapse_debug = build_case_collapse_candidates(claim_rows_debug)
        save_artifact(run_id, "claim_ledger_lite.json", json.dumps(claim_rows_debug, indent=2).encode("utf-8"))
        save_artifact(run_id, "case_collapse.json", json.dumps(collapse_debug, indent=2).encode("utf-8"))
        
    if evidence_graph_payload is not None:
        save_artifact(run_id, "evidence_graph.json", json.dumps(evidence_graph_payload, indent=2).encode("utf-8"))
    if patient_partitions_payload is not None:
        save_artifact(run_id, "patient_partitions.json", json.dumps(patient_partitions_payload, indent=2).encode("utf-8"))
    if missing_records_payload is not None:
        save_artifact(run_id, "missing_records.json", json.dumps(missing_records_payload, indent=2).encode("utf-8"))

    # PDF
    pdf_bytes = generate_pdf_from_projection(
        matter_title=matter_title,
        projection=projection,
        gaps=gaps,
        narrative_synthesis=narrative_synthesis,
        appendix_entries=appendix_projection.entries,
        raw_events=events,
        all_citations=all_citations,
        page_map=page_map,
        care_window=care_window,
        missing_records_payload=missing_records_payload,
    )
    pdf_path = save_artifact(run_id, "chronology.pdf", pdf_bytes)
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest() if hasattr(pdf_bytes, "__len__") else None
    if not pdf_sha:
        pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()

    # CSV
    csv_bytes = generate_csv_from_projection(projection)
    csv_path = save_artifact(run_id, "chronology.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()

    # DOCX
    docx_bytes = generate_docx(run_id, matter_title, events, gaps, providers, page_map, narrative_synthesis=narrative_synthesis)
    docx_path = save_artifact(run_id, "chronology.docx", docx_bytes)
    docx_sha = hashlib.sha256(docx_bytes).hexdigest()

    # Markdown
    md_bytes = build_markdown_bytes(
        projection=projection,
        matter_title=matter_title,
        events=events,
        narrative_synthesis=narrative_synthesis,
        clean_narrative_text=_clean_narrative_text,
        generate_executive_summary=generate_executive_summary,
        case_info=case_info,
    )
    save_artifact(run_id, "chronology.md", md_bytes)

    summary_text = _clean_narrative_text(narrative_synthesis) if narrative_synthesis else generate_executive_summary(events, matter_title, case_info=case_info)

    return ChronologyOutput(
        export_format_version="0.1.0",
        summary=summary_text,
        narrative_synthesis=narrative_synthesis,
        events_exported=exported_ids,
        exports=ChronologyExports(
            pdf=ArtifactRef(uri=str(pdf_path), sha256=pdf_sha, bytes=len(pdf_bytes)),
            csv=ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes)),
            docx=ArtifactRef(uri=str(docx_path), sha256=docx_sha, bytes=len(docx_bytes)),
            json_export=None,
        ),
    )


def render_patient_chronology_reports(
    run_id: str,
    matter_title: str,
    events: list[Event],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
    page_text_by_number: dict[int, str] | None = None,
) -> ArtifactRef | None:
    """Render one chronology PDF per detected patient and return manifest JSON artifact ref."""
    page_patient_labels = infer_page_patient_labels(page_text_by_number)
    projection = build_chronology_projection(
        events=events,
        providers=providers,
        page_map=page_map,
        page_patient_labels=page_patient_labels,
        page_text_by_number=page_text_by_number,
    )
    from collections import defaultdict
    grouped: dict[str, list] = defaultdict(list)
    for entry in projection.entries:
        if entry.patient_label == "Unknown Patient":
            continue
        grouped[entry.patient_label].append(entry)

    if len(grouped) < 2:
        return None

    manifest_rows: list[dict] = []
    for label in sorted(grouped.keys()):
        patient_projection = ChronologyProjection(
            generated_at=projection.generated_at,
            entries=grouped[label],
        )
        pdf_bytes = generate_pdf_from_projection(
            matter_title=f"{matter_title} - {label}",
            projection=patient_projection,
            gaps=[],
            narrative_synthesis=f"Patient-specific chronology for {label}.",
        )
        filename = f"chronology_patient_{_slugify(label)}.pdf"
        pdf_path = save_artifact(run_id, filename, pdf_bytes)
        pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
        manifest_rows.append({
            "patient_label": label,
            "event_count": len(patient_projection.entries),
            "artifact": {
                "type": "pdf",
                "filename": filename,
                "uri": str(pdf_path),
                "sha256": pdf_sha,
                "bytes": len(pdf_bytes),
            },
        })

    manifest = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "patients": manifest_rows,
    }
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    manifest_path = save_artifact(run_id, "patient_chronologies.json", manifest_bytes)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    return ArtifactRef(uri=str(manifest_path), sha256=manifest_sha, bytes=len(manifest_bytes))
