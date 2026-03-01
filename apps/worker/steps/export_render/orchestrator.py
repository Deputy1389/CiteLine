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
from apps.worker.project.chronology import build_chronology_projection, compute_provider_resolution_quality
from packages.shared.utils.render_utils import infer_page_patient_labels
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
from apps.worker.lib.litigation_safe_v1 import (
    build_litigation_safe_v1_snapshot,
    validate_litigation_safe_v1,
)
from apps.worker.lib.provider_resolution_v1 import augment_provider_resolution_quality
from apps.worker.lib.claim_context_alignment import run_claim_context_alignment
from apps.worker.steps.step_renderer_manifest import annotate_renderer_manifest_claim_context_alignment
from apps.worker.steps.export_render.projection_enrichment import (
    _enrich_projection_procedure_entries,
    _ensure_mri_bucket_entry,
    _ensure_procedure_bucket_entry,
    _ensure_ed_bucket_entry,
    _ensure_ortho_bucket_entry,
)
from packages.shared.utils.scoring_utils import bucket_for_required_coverage as _bucket_for_required_coverage
from apps.worker.steps.export_render.settlement_posture_pdf import render_settlement_posture_page
from apps.worker.lib.artifacts_writer import build_export_evidence_graph

if TYPE_CHECKING:
    from packages.shared.models import CaseInfo, Citation, Event, Gap, Provider


_MEDIATION_BANNED_KEYS = {
    "case_severity_index",
    "base_csi",
    "risk_adjusted_csi",
    "score_0_100",
    "weights",
    "penalty_total",
    "floor_applied",
    "ceiling_applied",
    "settlement_model_report",
    "settlement_leverage_model",
    "settlement_feature_pack",
    "defense_attack_map",
    "internal_demand_package",
}


def _normalize_export_mode(config) -> str:
    raw = str(getattr(config, "export_mode", "") or "").strip().upper()
    if raw not in {"INTERNAL", "MEDIATION"}:
        raise ValueError("export_mode is required and must be INTERNAL or MEDIATION")
    return raw


def _render_safe_evidence_graph_payload(evidence_graph_payload: dict | None, export_mode: str) -> dict | None:
    if not isinstance(evidence_graph_payload, dict):
        return evidence_graph_payload
    filtered = build_export_evidence_graph(evidence_graph_payload, export_mode)
    ext = filtered.get("extensions")
    if not isinstance(ext, dict):
        return {"extensions": {}}
    if export_mode != "MEDIATION":
        return {"extensions": dict(ext)}
    # Defense-in-depth on renderer input.
    clean_ext = {k: v for k, v in ext.items() if str(k) not in _MEDIATION_BANNED_KEYS}
    return {"extensions": clean_ext}


def render_exports(
    run_id: str,
    matter_title: str,
    events: list[Event],
    gaps: list[Gap],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
    page_provider_map: dict[int, str] | None = None,
    case_info: CaseInfo | None = None,
    all_citations: list[Citation] | None = None,
    narrative_synthesis: str | None = None,
    page_text_by_number: dict[int, str] | None = None,
    evidence_graph_payload: dict | None = None,
    patient_partitions_payload: dict | None = None,
    missing_records_payload: dict | None = None,
    specials_summary: dict | None = None,
    renderer_manifest: dict | None = None,
    config = None,
) -> ChronologyOutput:
    """
    Render all export formats, save to disk, and return ChronologyOutput.
    """
    provider_none_count = sum(1 for e in events if not e.provider_id or e.provider_id == "unknown")
    print(f"chronology_generation_input: {len(events)} events (provider_none_or_unknown={provider_none_count})")
    export_mode = _normalize_export_mode(config)
    
    projection_bundle = prepare_projection_bundle(
        events=events,
        providers=providers,
        page_map=page_map,
        page_provider_map=page_provider_map,
        page_text_by_number=page_text_by_number,
        narrative_synthesis=narrative_synthesis,
        missing_records_payload=missing_records_payload,
        config=config,
        build_chronology_projection=build_chronology_projection,
        infer_page_patient_labels=infer_page_patient_labels,
        enrich_projection_procedure_entries=_enrich_projection_procedure_entries,
        ensure_mri_bucket_entry=_ensure_mri_bucket_entry,
        ensure_procedure_bucket_entry=_ensure_procedure_bucket_entry,
        ensure_ed_bucket_entry=_ensure_ed_bucket_entry,
        ensure_ortho_bucket_entry=_ensure_ortho_bucket_entry,
        normalize_projection_patient_labels=_normalize_projection_patient_labels,
        merge_projection_entries_same_day=_merge_projection_entries_same_day,
        compute_care_window_from_projection=_compute_care_window_from_projection,
        apply_claim_guard_to_narrative=apply_claim_guard_to_narrative,
        repair_case_summary_narrative=_repair_case_summary_narrative,
        select_timeline=False,
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
    # Provider-resolution gate should be evaluated on timeline-select rows (attorney-facing chronology),
    # not appendix-style projection rows used for broader rendering context.
    provider_quality_bundle = prepare_projection_bundle(
        events=events,
        providers=providers,
        page_map=page_map,
        page_provider_map=page_provider_map,
        page_text_by_number=page_text_by_number,
        narrative_synthesis=None,
        missing_records_payload=None,
        config=config,
        build_chronology_projection=build_chronology_projection,
        infer_page_patient_labels=infer_page_patient_labels,
        enrich_projection_procedure_entries=_enrich_projection_procedure_entries,
        ensure_mri_bucket_entry=_ensure_mri_bucket_entry,
        ensure_procedure_bucket_entry=_ensure_procedure_bucket_entry,
        ensure_ed_bucket_entry=_ensure_ed_bucket_entry,
        ensure_ortho_bucket_entry=_ensure_ortho_bucket_entry,
        normalize_projection_patient_labels=_normalize_projection_patient_labels,
        merge_projection_entries_same_day=_merge_projection_entries_same_day,
        compute_care_window_from_projection=_compute_care_window_from_projection,
        apply_claim_guard_to_narrative=apply_claim_guard_to_narrative,
        repair_case_summary_narrative=_repair_case_summary_narrative,
        select_timeline=True,
    )
    provider_quality_projection = provider_quality_bundle["projection"]
    if isinstance(evidence_graph_payload, dict):
        ext = evidence_graph_payload.get("extensions")
        if not isinstance(ext, dict):
            ext = {}
            evidence_graph_payload["extensions"] = ext
        ext["export_mode"] = export_mode
        ext["export_artifacts_metadata"] = {
            "export_mode": export_mode,
            "pdf_suffix": f"_{export_mode}",
        }
        ext["provider_resolution_quality"] = augment_provider_resolution_quality(
            compute_provider_resolution_quality(provider_quality_projection.entries),
            pt_encounters=list(ext.get("pt_encounters") or []),
        )
        ext["claim_context_alignment"] = run_claim_context_alignment(
            evidence_graph_payload=evidence_graph_payload,
            renderer_manifest=renderer_manifest,
        )
        renderer_manifest = annotate_renderer_manifest_claim_context_alignment(renderer_manifest, ext)
        if isinstance(renderer_manifest, dict):
            ext["renderer_manifest"] = renderer_manifest
        billing_status = None
        if isinstance(renderer_manifest, dict):
            billing_status = str(renderer_manifest.get("billing_completeness") or "").strip().upper() or None
        pt_recon = ext.get("pt_reconciliation") if isinstance(ext.get("pt_reconciliation"), dict) else {}
        reported_pt_counts = list(pt_recon.get("reported_pt_counts") or []) if isinstance(pt_recon, dict) else []
        numeric_pt_counts = [
            ((renderer_manifest or {}).get("pt_summary") or {}).get("total_encounters")
            if isinstance(renderer_manifest, dict)
            else None
        ]
        numeric_pt_counts.extend(reported_pt_counts)
        ext["litigation_safe_v1"] = validate_litigation_safe_v1(
            build_litigation_safe_v1_snapshot(renderer_manifest),
            events,
            {
                "billingStatus": billing_status or "NONE",
                "gaps": gaps,
                "missing_records": missing_records_payload or ext.get("missing_records") or {},
                "renderer_manifest": renderer_manifest or {},
                "billingPresentation": {
                    "visibleIncompleteDisclosure": True,
                    "noGlobalTotalSpecials": True,
                    "partialTotalsLabeled": True,
                },
                "ptEvidence": pt_recon or {},
                "claimContextAlignment": ext.get("claim_context_alignment") or {},
                "numericAggregates": {
                    "pt_total_encounters": numeric_pt_counts,
                },
            },
        )
        missing_required = list(selection_meta.get("required_bucket_missing_after_selection") or []) if isinstance(selection_meta, dict) else []
        manifest_required_missing: list[str] = []
        manifest_bucket_evidence = (renderer_manifest or {}).get("bucket_evidence") if isinstance(renderer_manifest, dict) else {}
        if isinstance(manifest_bucket_evidence, dict):
            forced_required_event_buckets = (
                selection_meta.get("forced_required_event_buckets")
                if isinstance(selection_meta, dict)
                else {}
            )
            selected_buckets = {
                str(_bucket_for_required_coverage(entry) or "").strip()
                for entry in (projection.entries or [])
                if str(_bucket_for_required_coverage(entry) or "").strip()
            }
            if isinstance(forced_required_event_buckets, dict):
                selected_buckets.update(
                    str(bucket).strip()
                    for bucket in forced_required_event_buckets.values()
                    if str(bucket).strip()
                )
            for b in ("ed", "pt_eval"):
                payload = manifest_bucket_evidence.get(b)
                if not isinstance(payload, dict):
                    continue
                detected = bool(payload.get("detected"))
                has_ids = bool(payload.get("event_ids") or [])
                if (detected or has_ids) and b not in selected_buckets:
                    manifest_required_missing.append(b)
        if missing_required:
            sprint4d = ext.get("sprint4d_invariants") if isinstance(ext.get("sprint4d_invariants"), dict) else {}
            sprint4d["required_bucket_missing_after_selection"] = missing_required
            sprint4d["missing_required_buckets"] = sorted({str(item.get("bucket") or "").strip() for item in missing_required if str(item.get("bucket") or "").strip()})
            sprint4d["export_status"] = "BLOCKED_REQUIRED_BUCKET_SUPPRESSION"
            if "ed" in sprint4d.get("missing_required_buckets", []):
                sprint4d["ED_EXISTS_BUT_NOT_RENDERED"] = True
            ext["sprint4d_invariants"] = sprint4d
        if manifest_required_missing:
            sprint4d = ext.get("sprint4d_invariants") if isinstance(ext.get("sprint4d_invariants"), dict) else {}
            prior_missing = set(str(x).strip() for x in (sprint4d.get("missing_required_buckets") or []) if str(x).strip())
            prior_missing.update(manifest_required_missing)
            sprint4d["missing_required_buckets"] = sorted(prior_missing)
            sprint4d["required_bucket_missing_from_manifest"] = sorted(manifest_required_missing)
            if "ed" in sprint4d["missing_required_buckets"]:
                sprint4d["ED_EXISTS_BUT_NOT_RENDERED"] = True
            ext["sprint4d_invariants"] = sprint4d
    save_artifact(run_id, "selection_debug.json", json.dumps(selection_debug_payload, indent=2).encode("utf-8"))
    save_artifact(run_id, "claim_guard_report.json", json.dumps(claim_guard_report, indent=2).encode("utf-8"))
    
    debug_artifacts = str(os.getenv("DEBUG_ARTIFACTS", "false")).strip().lower() in {"1", "true", "yes", "on"}
    if debug_artifacts:
        claim_rows_debug = build_claim_ledger_lite(projection.entries, raw_events=events)
        collapse_debug = build_case_collapse_candidates(claim_rows_debug)
        save_artifact(run_id, "claim_ledger_lite.json", json.dumps(claim_rows_debug, indent=2).encode("utf-8"))
        save_artifact(run_id, "case_collapse.json", json.dumps(collapse_debug, indent=2).encode("utf-8"))
        
    mode_dir = f"exports/{export_mode.lower()}"
    if evidence_graph_payload is not None:
        bundle_payload = build_export_evidence_graph(evidence_graph_payload, export_mode)
        bundle_bytes = json.dumps(bundle_payload, indent=2).encode("utf-8")
        save_artifact(run_id, "evidence_graph.json", bundle_bytes)
        save_artifact(run_id, f"{mode_dir}/evidence_graph.json", bundle_bytes)
    save_artifact(
        run_id,
        "export_mode.json",
        json.dumps({"export_mode": export_mode, "generated_at": datetime.now(timezone.utc).isoformat()}, indent=2).encode("utf-8"),
    )
    if patient_partitions_payload is not None:
        save_artifact(run_id, "patient_partitions.json", json.dumps(patient_partitions_payload, indent=2).encode("utf-8"))
    if missing_records_payload is not None:
        save_artifact(run_id, "missing_records.json", json.dumps(missing_records_payload, indent=2).encode("utf-8"))

    render_payload = _render_safe_evidence_graph_payload(evidence_graph_payload, export_mode)
    if export_mode == "MEDIATION" and isinstance(render_payload, dict):
        non_ext_keys = [k for k in render_payload.keys() if str(k) != "extensions"]
        if non_ext_keys:
            raise RuntimeError(f"MEDIATION_RENDER_INPUT_BLOCKED: non-extension payload keys present: {', '.join(map(str, non_ext_keys))}")
        ext_check = render_payload.get("extensions")
        if isinstance(ext_check, dict):
            forbidden_in_mediation = {
                "settlement_model_report",
                "settlement_leverage_model",
                "settlement_feature_pack",
                "defense_attack_map",
                "case_severity_index",
            }
            leaked = sorted(k for k in forbidden_in_mediation if k in ext_check)
            if leaked:
                raise RuntimeError(f"MEDIATION_RENDER_INPUT_BLOCKED: forbidden settlement/valuation keys present: {', '.join(leaked)}")

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
        evidence_graph_payload=render_payload,
        specials_summary=specials_summary,
        renderer_manifest=renderer_manifest,
        run_id=run_id,
        include_internal_review_sections=False,
        export_mode=export_mode,
    )
    # Persist post-render extension updates (timeline audit / invariants) written during PDF generation.
    if evidence_graph_payload is not None:
        bundle_payload = build_export_evidence_graph(evidence_graph_payload, export_mode)
        bundle_bytes = json.dumps(bundle_payload, indent=2).encode("utf-8")
        save_artifact(run_id, "evidence_graph.json", bundle_bytes)
        save_artifact(run_id, f"{mode_dir}/evidence_graph.json", bundle_bytes)

    # Append settlement posture page to the PDF
    try:
        ext = (evidence_graph_payload or {}).get("extensions") if isinstance(evidence_graph_payload, dict) else {}
        if isinstance(ext, dict) and export_mode == "INTERNAL":
            _posture_bytes = render_settlement_posture_page(
                run_id=run_id,
                settlement_model_report=ext.get("settlement_model_report"),
                defense_attack_map=ext.get("defense_attack_map"),
                case_severity_index=ext.get("case_severity_index"),
            )
            if _posture_bytes:
                import io as _io
                from pypdf import PdfReader as _PdfReader, PdfWriter as _PdfWriter
                _writer = _PdfWriter()
                for _r in [_PdfReader(_io.BytesIO(pdf_bytes)), _PdfReader(_io.BytesIO(_posture_bytes))]:
                    for _p in _r.pages:
                        _writer.add_page(_p)
                _merged = _io.BytesIO()
                _writer.write(_merged)
                pdf_bytes = _merged.getvalue()
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"Settlement posture page append failed: {_exc}")

    pdf_path = save_artifact(run_id, "chronology.pdf", pdf_bytes)
    save_artifact(run_id, "export.pdf", pdf_bytes)
    save_artifact(run_id, f"{mode_dir}/chronology.pdf", pdf_bytes)
    save_artifact(run_id, f"{mode_dir}/export.pdf", pdf_bytes)
    save_artifact(run_id, f"chronology_{export_mode}.pdf", pdf_bytes)
    save_artifact(run_id, f"export_{export_mode}.pdf", pdf_bytes)
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
    page_provider_map: dict[int, str] | None = None,
    page_text_by_number: dict[int, str] | None = None,
    config = None,
) -> ArtifactRef | None:
    """Render one chronology PDF per detected patient and return manifest JSON artifact ref."""
    page_patient_labels = infer_page_patient_labels(page_text_by_number)
    export_mode = _normalize_export_mode(config)
    projection = build_chronology_projection(
        events=events,
        providers=providers,
        page_map=page_map,
        page_provider_map=page_provider_map,
        page_patient_labels=page_patient_labels,
        page_text_by_number=page_text_by_number,
        config=config,
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
            export_mode=export_mode,
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
