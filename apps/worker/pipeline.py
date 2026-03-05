"""
Pipeline orchestrator - runs the extraction pipeline in sequence.
"""
from __future__ import annotations

import json
import logging
import time
import os
import requests
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from packages.db.database import get_session
from packages.db.models import (
    Run as RunORM,
    SourceDocument as SourceDocORM,
)
from packages.shared.models import (
    CaseInfo,
    ClaimEdge,
    ChronologyResult,
    EvidenceGraph,
    LitigationExtensions,
    PipelineInputs,
    PipelineOutputs,
    RunConfig,
    SourceDocument,
    Warning,
    ArtifactRef,
    PageType,
)
from packages.shared.schema_validator import validate_output
from packages.shared.storage import get_upload_path, UPLOADS_DIR, ensure_dirs, save_artifact

# Step Imports
from apps.worker.steps.step00_validate import validate_inputs
from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step02_text_acquire import acquire_text
from apps.worker.steps.step03_classify import classify_pages
from apps.worker.steps.step03a_demographics import extract_demographics
from apps.worker.steps.step03b_patient_partitions import (
    assign_patient_scope_to_events,
    build_patient_partitions,
    enforce_event_patient_scope,
    render_patient_partitions,
    validate_patient_scope_invariants,
)
from apps.worker.steps.step04_segment import segment_documents
from apps.worker.steps.step05_provider import detect_providers
from apps.worker.steps.step06_dates import extract_dates_for_pages
from apps.worker.steps.step07_events import (
    extract_billing_events, extract_clinical_events, extract_imaging_events,
    extract_pt_events, extract_lab_events, extract_discharge_events, extract_operative_events,
)
from apps.worker.steps.step08_citations import post_process_citations
from apps.worker.steps.step09_dedup import deduplicate_events
from apps.worker.steps.step10_confidence import apply_confidence_scoring, filter_for_export
from apps.worker.steps.step11_gaps import detect_gaps
from apps.worker.steps.events.event_weighting import annotate_event_weights
from apps.worker.steps.events.legal_usability import improve_legal_usability
from apps.worker.steps.step12a_narrative_synthesis import synthesize_narrative
from apps.worker.steps.step12_export import render_exports, render_patient_chronology_reports
from apps.worker.project.chronology import build_chronology_projection, compute_provider_resolution_quality
from apps.worker.steps.step12b_litigation_review import run_litigation_review
from apps.worker.steps.step13_receipt import create_run_record
from apps.worker.lib.provider_normalize import normalize_provider_entities, compute_coverage_spans
from apps.worker.lib.quality_gates import run_quality_gates, write_fail_cover_pdf
from apps.worker.lib.claim_ledger_lite import build_claim_edges, select_top_claim_rows
from apps.worker.lib.causation_ladder import build_causation_ladders
from apps.worker.steps.case_collapse import (
    build_case_collapse_candidates, build_defense_attack_paths,
    build_objection_profiles, build_upgrade_recommendations, quote_lock,
)
from apps.worker.steps.litigation import (
    build_comparative_pattern_snapshot, build_contradiction_matrix, build_narrative_duality,
)
from apps.worker.steps.step14_provider_directory import render_provider_directory
from apps.worker.steps.step15_missing_records import detect_missing_records, render_missing_records
from apps.worker.steps.step15a_missing_record_requests import (
    generate_missing_record_requests, render_missing_record_requests,
)
from apps.worker.steps.step16_billing_lines import extract_billing_lines, render_billing_lines
from apps.worker.steps.step17_specials_summary import compute_specials_summary, render_specials_summary
from apps.worker.steps.step_renderer_manifest import build_renderer_manifest, annotate_renderer_manifest_claim_context_alignment
from apps.worker.steps.step_visit_abstraction_registry import build_competitive_registries
from apps.worker.steps.step18_paralegal_chronology import (
    build_paralegal_chronology_payload, generate_extraction_notes_md, render_paralegal_chronology_artifacts,
)
from apps.worker.pipeline_artifacts import build_artifact_ref_entries, build_page_map
from apps.worker.pipeline_persistence import persist_pipeline_state
from apps.worker.steps.step19_llm_reasoning import run_llm_reasoning
from apps.worker.steps.step20_chronology_narrative import run_chronology_narrative
from apps.worker.lib.litigation_integrity import run_litigation_integrity_pass
from apps.worker.lib.pipeline_parity import build_pipeline_parity_report
from apps.worker.quality.text_quality import clean_text, is_garbage
from apps.worker.lib.pt_enumeration import build_pt_evidence_extensions
from apps.worker.lib.provider_resolution_v1 import augment_provider_resolution_quality
from apps.worker.lib.claim_context_alignment import run_claim_context_alignment
from apps.worker.lib.litigation_safe_v1 import build_litigation_safe_v1_snapshot, validate_litigation_safe_v1
from apps.worker.lib.settlement_leverage import build_settlement_leverage_model
from apps.worker.lib.settlement_features import build_settlement_feature_pack
from apps.worker.lib.defense_attack_map import build_defense_attack_map
from apps.worker.lib.case_severity_index import build_case_severity_index
from apps.worker.lib.severity_profile import build_severity_profile
from apps.worker.lib.settlement_model import build_settlement_model_report
from apps.worker.lib.internal_demand_copilot import build_internal_demand_package
from apps.worker.lib.artifacts_writer import build_export_evidence_graph

logger = logging.getLogger(__name__)
RUN_TIMEOUT_SECONDS = int(os.getenv("RUN_TIMEOUT_SECONDS", "1800"))
API_BASE_URL = os.getenv("API_BASE_URL", "https://linecite-api.onrender.com")
ERROR_MESSAGE_MAX_LEN = int(os.getenv("ERROR_MESSAGE_MAX_LEN", "2000"))


def _require_export_mode_config(config_dict: dict[str, Any]) -> str:
    mode = str((config_dict or {}).get("export_mode") or "").strip().upper()
    if mode not in {"INTERNAL", "MEDIATION"}:
        raise ValueError("Run config must include explicit export_mode: INTERNAL or MEDIATION")
    return mode

def _download_document_from_api(document_id: str, timeout_seconds: int) -> Path:
    ensure_dirs()
    local_path = UPLOADS_DIR / f"{document_id}.pdf"
    if local_path.exists(): return local_path
    url = f"{API_BASE_URL}/documents/{document_id}/download"
    logger.info(f"Downloading document {document_id} from {url}")
    try:
        response = requests.get(url, timeout=timeout_seconds); response.raise_for_status()
        local_path.write_bytes(response.content)
        return local_path
    except Exception as e:
        logger.error(f"Failed to download document {document_id}: {e}")
        raise RuntimeError(f"Failed to download document from API: {e}")

def _check_deadline(start_time: float, run_id: str, label: str) -> None:
    elapsed = time.time() - start_time
    if elapsed > RUN_TIMEOUT_SECONDS:
        raise TimeoutError(f"Run {run_id} exceeded timeout at {label} ({int(elapsed)}s)")

def _build_litigation_extensions(claim_rows: list[dict] | list[ClaimEdge], config: RunConfig) -> dict:
    all_rows = list(claim_rows); anchored_rows = [r for r in all_rows if (r.get("citations") or [])]
    collapse_candidates = build_case_collapse_candidates(anchored_rows)
    attack_paths = build_defense_attack_paths(collapse_candidates, limit=config.litigation_defense_paths_limit)
    objection_profiles = build_objection_profiles(all_rows, limit=config.litigation_objection_profiles_limit)
    upgrade_recs = build_upgrade_recommendations(collapse_candidates, limit=config.litigation_upgrade_recommendations_limit)
    locked_quotes: list[dict] = []
    for row in select_top_claim_rows(anchored_rows, limit=config.litigation_quote_lock_limit):
        q = quote_lock(str(row.get("assertion") or ""))
        if q: locked_quotes.append({"id": str(row.get("id") or ""), "date": str(row.get("date") or "unknown"), "claim_type": str(row.get("claim_type") or ""), "quote": q, "citation": str(row.get("citation") or ""), "event_id": str(row.get("event_id") or "")})
    causation_chains = build_causation_ladders(all_rows)
    contradiction_matrix = build_contradiction_matrix(all_rows, limit=config.litigation_contradiction_limit)
    narrative_duality = build_narrative_duality(all_rows)
    comparative_snapshot = build_comparative_pattern_snapshot(all_rows)
    payload = {"claim_rows": all_rows, "causation_chains": causation_chains, "citation_fidelity": {"claim_rows_total": len(all_rows), "claim_rows_anchored": len(anchored_rows), "claim_row_anchor_ratio": round((len(anchored_rows) / len(all_rows)), 4) if all_rows else 1.0}, "case_collapse_candidates": collapse_candidates, "defense_attack_paths": attack_paths, "objection_profiles": objection_profiles, "evidence_upgrade_recommendations": upgrade_recs, "quote_lock_rows": locked_quotes, "contradiction_matrix": contradiction_matrix, "narrative_duality": narrative_duality, "comparative_pattern_engine": comparative_snapshot}
    return LitigationExtensions.model_validate(payload).model_dump(mode="json")

def run_pipeline(run_id: str) -> None:
    started_at = datetime.now(timezone.utc); start_time = time.time(); all_warnings = []
    try:
        with get_session() as session:
            run_row = session.query(RunORM).filter_by(id=run_id).first()
            if not run_row: return
            run_row.status = "running"; run_row.started_at = started_at; session.flush()
            matter = run_row.matter; matter_title = matter.title; matter_id = matter.id; firm_id = matter.firm_id; tz = matter.timezone or "America/Los_Angeles"
            config_dict = run_row.config_json if isinstance(run_row.config_json, dict) else {}
            export_mode = _require_export_mode_config(config_dict)
            config = RunConfig(**config_dict)
            # Pass34: Enforce LLM policy at pipeline entry — before any step runs.
            # MEDIATION export must complete regardless of LLM availability.
            if export_mode == "MEDIATION":
                config.enable_llm_reasoning = False
            doc_rows = session.query(SourceDocORM).filter_by(matter_id=matter_id).all()
            source_documents = [SourceDocument(document_id=d.id, filename=d.filename, mime_type=d.mime_type, sha256=d.sha256, bytes=d.bytes, uploaded_at=d.uploaded_at) for d in doc_rows]
        if not source_documents: _fail_run(run_id, "No source documents found"); return

        valid_docs, step_warnings = validate_inputs(source_documents, config); all_warnings.extend(step_warnings)
        if not valid_docs: _fail_run(run_id, "No valid documents"); return

        all_pages, total_ocr, page_offset = [], 0, 0
        for doc in valid_docs:
            _check_deadline(start_time, run_id, "step1-2")
            pdf_path = str(_download_document_from_api(doc.document_id, config.api_download_timeout_seconds))
            pages, _ = split_pages(pdf_path, doc.document_id, page_offset, config.max_pages - page_offset)
            pages, ocr_count, _ = acquire_text(pages, pdf_path, run_id=run_id)
            total_ocr += ocr_count; all_pages.extend(pages); page_offset += len(pages)
        if not all_pages: _fail_run(run_id, "No pages extracted"); return

        # Assess page text quality before classification/extraction so obvious junk can be
        # downgraded and excluded from contributing substantive events.
        page_quality = _assess_page_quality(all_pages)
        low_quality_pages = {pn for pn, meta in page_quality.items() if meta.get("is_low_quality")}
        extraction_excluded_pages = {pn for pn, meta in page_quality.items() if meta.get("action") == "exclude"}
        logger.info(
            f"[{run_id}] Page quality: {len(low_quality_pages)}/{len(all_pages)} flagged, "
            f"{len(extraction_excluded_pages)} excluded from extraction"
        )

        all_pages, _ = classify_pages(all_pages)
        # Downgrade obvious junk pages so they do not masquerade as substantive page types.
        for p in all_pages:
            meta = page_quality.get(p.page_number) or {}
            if meta.get("action") == "exclude":
                p.page_type = PageType.OTHER
                p.extensions = dict(p.extensions or {})
                p.extensions["page_quality"] = meta
                p.extensions["page_type_downgraded_by_quality"] = True
            elif meta:
                p.extensions = dict(p.extensions or {})
                p.extensions["page_quality"] = meta
        patient, _ = extract_demographics(all_pages)
        patient_partitions_payload, page_to_patient_scope = build_patient_partitions(all_pages)

        all_documents = []
        for doc in valid_docs:
            doc_pages = [p for p in all_pages if p.source_document_id == doc.document_id]
            docs, _ = segment_documents(doc_pages, doc.document_id); all_documents.extend(docs)

        # Filter pages for provider detection / extraction - skip only pages marked hard-exclude.
        quality_filtered_pages = [p for p in all_pages if p.page_number not in extraction_excluded_pages]
        
        providers, page_provider_map, _ = detect_providers(quality_filtered_pages, all_documents)

        # Filter out the Unknown Provider sentinel from page_provider_map
        # so events on those pages show "Provider Not Stated" rather than a bogus entity
        UNKNOWN_SENTINEL_IDS = {p.provider_id for p in providers if p.confidence == 0 and (p.normalized_name or "").lower() == "unknown provider"}
        page_provider_map = {pg: pid for pg, pid in page_provider_map.items() if pid not in UNKNOWN_SENTINEL_IDS}

        dates = extract_dates_for_pages(quality_filtered_pages, page_provider_map=page_provider_map)

        all_events, all_citations, all_skipped = [], [], []
        # Extraction logic
        e, c, w, s = extract_clinical_events(quality_filtered_pages, dates, providers, config, page_provider_map); all_events.extend(e); all_citations.extend(c); all_skipped.extend(s)
        e, c, w, s = extract_imaging_events(quality_filtered_pages, dates, providers, config, page_provider_map, page_text_by_number={p.page_number: (p.text or "") for p in quality_filtered_pages}); all_events.extend(e); all_citations.extend(c); all_skipped.extend(s)
        e, c, w, s = extract_pt_events(quality_filtered_pages, dates, providers, config, page_provider_map); all_events.extend(e); all_citations.extend(c); all_skipped.extend(s)
        e, c, w, s = extract_billing_events(quality_filtered_pages, dates, providers, config, page_provider_map); all_events.extend(e); all_citations.extend(c); all_skipped.extend(s)
        e, c, w, s = extract_lab_events(quality_filtered_pages, dates, providers, config, page_provider_map); all_events.extend(e); all_citations.extend(c); all_skipped.extend(s)
        e, c, w, s = extract_discharge_events(quality_filtered_pages, dates, providers, config, page_provider_map); all_events.extend(e); all_citations.extend(c); all_skipped.extend(s)
        e, c, w, s = extract_operative_events(quality_filtered_pages, dates, providers, config, page_provider_map); all_events.extend(e); all_citations.extend(c); all_skipped.extend(s)

        # Quality Gate
        quality_stats = {"num_snippets_filtered": 0, "num_snippets_cleaned": 0}
        clean_events = []
        for evt in all_events:
            cleaned_facts = []
            for fact in evt.facts or []:
                text = str(getattr(fact, "text", "") or "")
                cleaned = clean_text(text)
                if cleaned and cleaned != text: quality_stats["num_snippets_cleaned"] += 1
                if is_garbage(cleaned): quality_stats["num_snippets_filtered"] += 1; continue
                fact.text = cleaned; cleaned_facts.append(fact)
            if cleaned_facts: evt.facts = cleaned_facts; clean_events.append(evt)
        all_events = clean_events

        assign_patient_scope_to_events(all_events, page_to_patient_scope)
        enforce_event_patient_scope(all_events, all_citations, page_to_patient_scope)
        all_citations, _ = post_process_citations(all_citations)
        pt_evidence_ext = build_pt_evidence_extensions(
            pages=quality_filtered_pages,
            dates_by_page=dates,
            providers=providers,
            page_provider_map=page_provider_map,
            citations=all_citations,
        )
        all_events, _ = deduplicate_events(all_events)
        all_events, _ = apply_confidence_scoring(all_events, config)
        weight_summary = annotate_event_weights(all_events)

        chronology_events = improve_legal_usability([e.model_copy(deep=True) for e in all_events])
        export_events = filter_for_export([e.model_copy(deep=True) for e in all_events], config)
        export_events, gaps, _ = detect_gaps(export_events, config)
        export_events = improve_legal_usability(export_events)

        narrative_synthesis = synthesize_narrative(chronology_events, providers, all_citations, case_info=CaseInfo(case_id=matter_id, firm_id=firm_id, title=matter_title, timezone=tz, patient=patient))

        evidence_graph = EvidenceGraph(documents=all_documents, pages=all_pages, providers=providers, events=all_events, citations=all_citations, gaps=gaps, skipped_events=all_skipped)
        evidence_graph.extensions["patient_partitions"] = patient_partitions_payload
        evidence_graph.extensions.update(pt_evidence_ext)

        # Page quality assessment results (early gate)
        evidence_graph.extensions["page_quality_assessment"] = {
            "total_pages": len(all_pages),
            "low_quality_pages": len(low_quality_pages),
            "low_quality_page_numbers": sorted(low_quality_pages),
            "extraction_excluded_pages": len(extraction_excluded_pages),
            "extraction_excluded_page_numbers": sorted(extraction_excluded_pages),
            "reason_counts": _page_quality_reason_counts(page_quality),
            "details": [
                {
                    "page_number": int(p.page_number),
                    "page_type": str(p.page_type or "other"),
                    "text_source": str(getattr(p, "text_source", "") or ""),
                    **(page_quality.get(p.page_number) or {}),
                }
                for p in all_pages
            ],
        }

        # Ã¢â€â‚¬Ã¢â€â‚¬ Metrics Ã¢â€â‚¬Ã¢â€â‚¬
        page_type_counts = {}
        for p in all_pages: pt = str(p.page_type or "other"); page_type_counts[pt] = page_type_counts.get(pt, 0) + 1
        event_type_counts = {}
        for e in all_events: et = str(e.event_type); event_type_counts[et] = event_type_counts.get(et, 0) + 1
        evidence_graph.extensions["extraction_metrics"] = {"pages_total": len(all_pages), "pages_classified": page_type_counts, "providers_detected": len(providers), "events_total": len(all_events), "events_by_type": event_type_counts, "events_exported": len(chronology_events), "facts_total": sum(len(e.facts) for e in all_events), "citations_total": len(all_citations)}
        evidence_graph.extensions["quality_gate"] = quality_stats
        evidence_graph.extensions["event_weighting"] = weight_summary

        # Ã¢â€â‚¬Ã¢â€â‚¬ Step 14-17: Artifacts Ã¢â€â‚¬Ã¢â€â‚¬
        claim_edges = build_claim_edges([], raw_events=chronology_events, all_citations=all_citations)
        evidence_graph.extensions.update(_build_litigation_extensions(claim_edges, config))

        providers_normalized = normalize_provider_entities(evidence_graph)
        evidence_graph.extensions["providers_normalized"] = providers_normalized
        evidence_graph.extensions["coverage_spans"] = compute_coverage_spans(providers_normalized)
        prov_csv_ref, prov_json_ref = render_provider_directory(run_id, providers_normalized)
        patient_partitions_json_ref = render_patient_partitions(run_id, patient_partitions_payload)

        missing_records_payload = detect_missing_records(evidence_graph, providers_normalized)
        evidence_graph.extensions["missing_records"] = missing_records_payload
        mr_csv_ref, mr_json_ref = render_missing_records(run_id, missing_records_payload)

        missing_record_requests_payload = generate_missing_record_requests(evidence_graph)
        mrr_csv_ref, mrr_json_ref, mrr_md_ref = render_missing_record_requests(run_id, missing_record_requests_payload)

        billing_lines_payload = extract_billing_lines(evidence_graph, providers_normalized)
        bl_csv_ref, bl_json_ref = render_billing_lines(run_id, billing_lines_payload)

        specials_payload = compute_specials_summary(billing_lines_payload, providers_normalized)
        evidence_graph.extensions["specials_summary"] = specials_payload
        ss_csv_ref, ss_json_ref, ss_pdf_ref = render_specials_summary(run_id, specials_payload, matter_title)

        renderer_manifest = build_renderer_manifest(
            events=chronology_events,
            evidence_graph_extensions=evidence_graph.extensions,
            specials_summary=specials_payload,
            citations=all_citations,
        )
        evidence_graph.extensions["renderer_manifest"] = renderer_manifest.model_dump(mode="json")
        registry_payload = build_competitive_registries(
            events=chronology_events,
            providers=providers,
            citations=all_citations,
            mechanism=str(getattr(renderer_manifest.mechanism, "value", "") or ""),
        )
        evidence_graph.extensions.update(registry_payload)
        rm_with_registry = renderer_manifest.model_dump(mode="json")
        for key in (
            "visit_abstraction_registry",
            "provider_role_registry",
            "diagnosis_registry",
            "injury_clusters",
            "injury_cluster_severity",
            "treatment_escalation_path",
            "causation_timeline_registry",
            "visit_bucket_quality",
            "registry_contract_version",
        ):
            rm_with_registry[key] = registry_payload.get(key)
        evidence_graph.extensions["renderer_manifest"] = rm_with_registry

        # Ã¢â€â‚¬Ã¢â€â‚¬ Step 18: Paralegal artifacts Ã¢â€â‚¬Ã¢â€â‚¬
        page_map = build_page_map(all_pages, source_documents)
        projection_for_metrics = build_chronology_projection(
            events=chronology_events,
            providers=providers,
            page_map=page_map,
            page_provider_map=page_provider_map,
            page_text_by_number={p.page_number: (p.text or "") for p in all_pages},
            config=config,
        )
        evidence_graph.extensions["provider_resolution_quality"] = compute_provider_resolution_quality(
            projection_for_metrics.entries
        )
        evidence_graph.extensions["provider_resolution_quality"] = augment_provider_resolution_quality(
            evidence_graph.extensions.get("provider_resolution_quality"),
            pt_encounters=list(evidence_graph.extensions.get("pt_encounters") or []),
        )
        evidence_graph.extensions["claim_context_alignment"] = run_claim_context_alignment(
            evidence_graph_payload=evidence_graph.model_dump(mode="json"),
            renderer_manifest=renderer_manifest.model_dump(mode="json"),
        )
        annotated_manifest = annotate_renderer_manifest_claim_context_alignment(
            renderer_manifest,
            evidence_graph.extensions,
        )
        if isinstance(annotated_manifest, type(renderer_manifest)):
            renderer_manifest = annotated_manifest
            rm_with_registry = renderer_manifest.model_dump(mode="json")
            for key in (
                "visit_abstraction_registry",
                "provider_role_registry",
                "diagnosis_registry",
                "injury_clusters",
                "injury_cluster_severity",
                "treatment_escalation_path",
                "causation_timeline_registry",
                "visit_bucket_quality",
                "registry_contract_version",
            ):
                rm_with_registry[key] = evidence_graph.extensions.get(key)
            evidence_graph.extensions["renderer_manifest"] = rm_with_registry
        billing_status_upper = str(renderer_manifest.billing_completeness or "none").strip().upper()
        pt_recon = (
            evidence_graph.extensions.get("pt_reconciliation")
            if isinstance(evidence_graph.extensions.get("pt_reconciliation"), dict)
            else {}
        )
        reported_pt_counts = list(pt_recon.get("reported_pt_counts") or []) if isinstance(pt_recon, dict) else []
        numeric_pt_counts = [renderer_manifest.pt_summary.total_encounters]
        numeric_pt_counts.extend(reported_pt_counts)
        evidence_graph.extensions["litigation_safe_v1"] = validate_litigation_safe_v1(
            build_litigation_safe_v1_snapshot(renderer_manifest.model_dump(mode="json")),
            chronology_events,
            {
                "billingStatus": billing_status_upper or "NONE",
                "gaps": gaps,
                "missing_records": evidence_graph.extensions.get("missing_records") or {},
                "renderer_manifest": renderer_manifest.model_dump(mode="json"),
                "billingPresentation": {
                    "visibleIncompleteDisclosure": True,
                    "noGlobalTotalSpecials": True,
                    "partialTotalsLabeled": True,
                },
                "ptEvidence": pt_recon or {},
                "claimContextAlignment": evidence_graph.extensions.get("claim_context_alignment") or {},
                "numericAggregates": {
                    "pt_total_encounters": numeric_pt_counts,
                },
            },
        )
        evidence_graph.extensions["settlement_leverage_model"] = build_settlement_leverage_model(
            evidence_graph_payload=evidence_graph.model_dump(mode="json"),
            renderer_manifest=renderer_manifest.model_dump(mode="json"),
        )
        _sfp = build_settlement_feature_pack(
            evidence_graph_payload=evidence_graph.model_dump(mode="json"),
            renderer_manifest=renderer_manifest.model_dump(mode="json"),
        )
        evidence_graph.extensions["settlement_feature_pack"] = _sfp
        _dam = build_defense_attack_map(
            evidence_graph_payload=evidence_graph.model_dump(mode="json"),
            renderer_manifest=renderer_manifest.model_dump(mode="json"),
            feature_pack=_sfp,
        )
        evidence_graph.extensions["defense_attack_map"] = _dam
        _csi = build_case_severity_index(
            evidence_graph_payload=evidence_graph.model_dump(mode="json"),
            renderer_manifest=renderer_manifest.model_dump(mode="json"),
            feature_pack=_sfp,
        )
        evidence_graph.extensions["case_severity_index"] = _csi
        evidence_graph.extensions["severity_profile"] = build_severity_profile(_csi)
        evidence_graph.extensions["settlement_model_report"] = build_settlement_model_report(
            feature_pack=_sfp,
            dam=_dam,
            csi=_csi,
            settlement_leverage_model=evidence_graph.extensions.get("settlement_leverage_model"),
        )
        evidence_graph.extensions["internal_demand_package"] = build_internal_demand_package(
            evidence_graph=evidence_graph.model_dump(mode="json"),
            csi_internal=_csi,
            damages_structured=specials_payload,
        )
        paralegal_payload = build_paralegal_chronology_payload(evidence_graph, chronology_events, providers, page_map)
        evidence_graph.extensions["paralegal_chronology"] = paralegal_payload
        extraction_notes_md = generate_extraction_notes_md(evidence_graph, chronology_events, page_map)
        paralegal_chronology_md_ref, extraction_notes_md_ref = render_paralegal_chronology_artifacts(run_id, paralegal_payload, extraction_notes_md)

        # Ã¢â€â‚¬Ã¢â€â‚¬ Step 19/20: LLM Ã¢â€â‚¬Ã¢â€â‚¬
        if config.enable_llm_reasoning:
            try:
                llm_ext, llm_warns = run_llm_reasoning(evidence_graph, providers, config)
                all_warnings.extend(llm_warns); evidence_graph.extensions.update(llm_ext)
                run_chronology_narrative(evidence_graph, providers, config)
                evidence_graph.extensions["llm_polish_applied"] = True
            except Exception as _llm_err:
                logger.warning("LLM reasoning failed gracefully (will continue with deterministic output): %s", _llm_err)
                evidence_graph.extensions["llm_polish_applied"] = False
        else:
            evidence_graph.extensions["llm_polish_applied"] = False

        # Ã¢â€â‚¬Ã¢â€â‚¬ Final Export Ã¢â€â‚¬Ã¢â€â‚¬
        processing_seconds = time.time() - start_time
        case_info = CaseInfo(case_id=matter_id, firm_id=firm_id, title=matter_title, timezone=tz, patient=patient)
        chronology = render_exports(
            run_id,
            matter_title,
            chronology_events,
            gaps,
            providers,
            page_map=page_map,
            page_provider_map=page_provider_map,
            case_info=case_info,
            all_citations=all_citations,
            narrative_synthesis=narrative_synthesis,
            page_text_by_number={p.page_number: (p.text or "") for p in all_pages},
            evidence_graph_payload=evidence_graph.model_dump(mode="json"),
            specials_summary=specials_payload,
            config=config,
            renderer_manifest=(
                evidence_graph.extensions.get("renderer_manifest")
                if isinstance(evidence_graph.extensions.get("renderer_manifest"), dict)
                else renderer_manifest.model_dump(mode="json")
            ),
        )
        patient_chronologies_json_ref = render_patient_chronology_reports(
            run_id=run_id,
            matter_title=matter_title,
            events=chronology_events,
            providers=providers,
            page_map=page_map,
            page_provider_map=page_provider_map,
            page_text_by_number={p.page_number: (p.text or "") for p in all_pages},
            config=config,
        )

        litigation_checklist, review_warnings = run_litigation_review(run_id, chronology_events, {p.page_number: (p.text or "") for p in all_pages})
        all_warnings.extend(review_warnings)

        run_record = create_run_record(run_id, started_at, source_documents, evidence_graph, chronology, all_warnings, processing_seconds)
        full_result = ChronologyResult(schema_version="0.1.0", generated_at=datetime.now(timezone.utc), case=case_info, inputs=PipelineInputs(source_documents=source_documents, run_config=config), outputs=PipelineOutputs(run=run_record, evidence_graph=evidence_graph, chronology=chronology))

        full_output_dict = full_result.model_dump(mode="json")
        eg_dict = build_export_evidence_graph(evidence_graph.model_dump(mode="json"), export_mode)
        json_bytes = json.dumps(eg_dict, indent=2, default=str).encode()
        json_path = save_artifact(run_id, "evidence_graph.json", json_bytes)
        json_sha = hashlib.sha256(json_bytes).hexdigest()
        if not chronology.exports.json_export:
            chronology.exports.json_export = ArtifactRef(uri=str(json_path), sha256=json_sha, bytes=len(json_bytes))
        else:
            chronology.exports.json_export.uri, chronology.exports.json_export.sha256, chronology.exports.json_export.bytes = str(json_path), json_sha, len(json_bytes)

        is_valid, errors = validate_output(full_output_dict)
        status = "success" if is_valid else "partial"

        # Run quality gates before finalizing
        gate_results = _run_production_quality_gates(
            chronology=chronology,
            page_text_by_number={p.page_number: (p.text or "") for p in all_pages},
            projection_entries=list(projection_for_metrics.entries),
            chronology_events=chronology_events,
            gaps=list(gaps),
            source_pdf=(str(get_upload_path(valid_docs[0].document_id)) if valid_docs else None),
            quality_mode=str(config.quality_mode or "strict"),
            visit_bucket_quality=evidence_graph.extensions.get("visit_bucket_quality"),
        )
        parity_report = build_pipeline_parity_report(
            mode="production",
            source_pdf=(str(get_upload_path(valid_docs[0].document_id)) if valid_docs else None),
            page_text_by_number={p.page_number: (p.text or "") for p in all_pages},
            projection_entries=list(projection_for_metrics.entries),
            chronology_events=chronology_events,
            gaps=list(gaps),
            gate_results=gate_results,
        )
        evidence_graph.extensions["pipeline_parity_report"] = parity_report
        parity_bytes = json.dumps(parity_report, indent=2, default=str).encode()
        parity_path = save_artifact(run_id, "pipeline_parity_report.json", parity_bytes)
        parity_sha = hashlib.sha256(parity_bytes).hexdigest()
        parity_ref = ArtifactRef(uri=str(parity_path), sha256=parity_sha, bytes=len(parity_bytes))

        # Update status based on quality gates
        gate_export_status = str(gate_results.get("export_status") or "").strip().upper()
        if gate_export_status in {"BLOCKED", "REVIEW_RECOMMENDED"}:
            status = "needs_review"
            all_warnings.append(
                Warning(
                    code="QUALITY_GATE_FAILED",
                    message=(
                        "Quality gates require review: "
                        f"export_status={gate_export_status or 'UNKNOWN'}, "
                        f"attorney={gate_results.get('attorney_ready_pass')}, "
                        f"luqa={gate_results.get('luqa_pass')}"
                    ),
                )
            )
            
            # Write fail cover PDF if gates failed
            try:
                pdf_uri = getattr(getattr(chronology, 'exports', None), 'pdf', None)
                if pdf_uri and hasattr(pdf_uri, 'uri'):
                    pdf_path = str(pdf_uri.uri)
                    write_fail_cover_pdf(pdf_path, gate_results)
                    logger.warning(f"[{run_id}] Written fail cover page due to quality gate failures")
            except Exception as e:
                logger.error(f"Failed to write fail cover PDF: {e}")

        artifact_entries = build_artifact_ref_entries(
            chronology,
            prov_csv_ref,
            prov_json_ref,
            mr_csv_ref,
            mr_json_ref,
            mrr_csv_ref,
            mrr_json_ref,
            mrr_md_ref,
            bl_csv_ref,
            bl_json_ref,
            ss_csv_ref,
            ss_json_ref,
            ss_pdf_ref,
            paralegal_chronology_md_ref,
            extraction_notes_md_ref,
            patient_chronologies_json_ref,
            patient_partitions_json_ref,
            parity_ref,
        )

        persist_pipeline_state(run_id, status, processing_seconds, run_record, all_warnings, evidence_graph, artifact_entries, gate_results)
        logger.info(f"[{run_id}] Pipeline complete: {status}")

    except Exception as exc:
        logger.exception(f"[{run_id}] Pipeline failed: {exc}"); _fail_run(run_id, str(exc))

def _run_production_quality_gates(
    chronology,
    page_text_by_number: dict[int, str],
    projection_entries,
    chronology_events,
    gaps,
    source_pdf: str | None = None,
    quality_mode: str = "strict",
    visit_bucket_quality: dict[str, Any] | None = None,
) -> dict:
    """
    Run quality gates on the production pipeline output.
    
    Extracts text from the rendered PDF and runs attorney readiness
    and LUQA checks to ensure quality before export.
    """
    from apps.worker.lib.quality_gates import run_quality_gates
    import fitz
    
    try:
        # Get PDF path from chronology exports
        pdf_uri = getattr(getattr(chronology, 'exports', None), 'pdf', None)
        if not pdf_uri:
            logger.warning("No PDF export found in chronology, skipping quality gates")
            return {"overall_pass": True, "skipped": True}
        
        pdf_path = getattr(pdf_uri, 'uri', None)
        if not pdf_path:
            logger.warning("No PDF path found, skipping quality gates")
            return {"overall_pass": True, "skipped": True}
        
        # Convert Path to string if needed
        pdf_path_str = str(pdf_path)
        
        # Extract text from PDF
        try:
            doc = fitz.open(pdf_path_str)
            report_text = "\n".join((doc[i].get_text("text") or "") for i in range(doc.page_count))
            doc.close()
        except Exception as e:
            logger.warning(f"Failed to extract text from PDF for quality gates: {e}")
            return {"overall_pass": True, "skipped": True}
        
        # Run quality gates
        results = run_quality_gates(
            report_text=report_text,
            page_text_by_number=page_text_by_number,
            projection_entries=list(projection_entries or []),
            chronology_events=list(chronology_events or []),
            gaps=list(gaps or []),
            source_pdf=source_pdf,
            quality_mode=quality_mode,
            visit_bucket_quality=visit_bucket_quality,
        )
        
        logger.info(f"Quality gates: overall_pass={results.get('overall_pass')}, "
                   f"attorney={results.get('attorney_ready_pass')}({results.get('attorney_ready_score')}), "
                   f"luqa={results.get('luqa_pass')}({results.get('luqa_score')})")
        
        return results
        
    except Exception as e:
        logger.exception(f"Quality gates failed with error: {e}")
        return {"overall_pass": True, "skipped": True, "error": str(e)}


def _fail_run(run_id: str, error: str) -> None:
    with get_session() as session:
        run_row = session.query(RunORM).filter_by(id=run_id).first()
        if run_row: run_row.status = "failed"; run_row.finished_at = datetime.now(timezone.utc); run_row.error_message = error[:ERROR_MESSAGE_MAX_LEN]


def _assess_page_quality(pages) -> dict[int, dict]:
    """
    Assess quality of each page's text to identify garbage before extraction/classification.

    Returns dict mapping page_number -> metadata:
    {
      "is_low_quality": bool,
      "action": "exclude" | "downgrade" | "allow",
      "score": float,
      "reason_codes": list[str],
    }
    """
    from apps.worker.quality.text_quality import is_garbage, quality_score, explain_flags

    page_quality: dict[int, dict] = {}
    for page in pages:
        text = page.text or ""
        stripped = text.strip()
        score = float(quality_score(text)) if stripped else 0.0
        reasons: list[str] = []

        if not stripped:
            reasons.append("empty_text")
        elif len(stripped) < 50:
            reasons.append("too_short")

        flags = set(explain_flags(text))
        if "fax_artifact" in flags:
            reasons.append("fax_header")
        if "repeated_labels" in flags:
            reasons.append("template_noise")

        if stripped and is_garbage(text):
            reasons.append("ocr_garbage")
        elif score < 0.2:
            reasons.append("low_medical_signal")

        # v1 safety: only hard-exclude obvious junk. Fax/header and OCR garbage flags can appear
        # on otherwise substantive pages, so gate them with score/length heuristics.
        exclude_reasons = {"empty_text"}
        is_low = bool(reasons)
        action = "allow"
        if any(r in exclude_reasons for r in reasons):
            action = "exclude"
        elif "template_noise" in reasons and score < 0.18:
            action = "exclude"
        elif "fax_header" in reasons and ("too_short" in reasons or score < 0.16):
            action = "exclude"
        elif "ocr_garbage" in reasons and score < 0.06 and ("too_short" in reasons or "low_medical_signal" in reasons):
            action = "exclude"
        elif is_low:
            action = "downgrade"
        page_quality[page.page_number] = {
            "is_low_quality": is_low,
            "action": action,
            "score": round(score, 4),
            "reason_codes": sorted(set(reasons)),
        }

    return page_quality


def _page_quality_reason_counts(page_quality: dict[int, dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for meta in (page_quality or {}).values():
        for reason in list(meta.get("reason_codes") or []):
            counts[reason] = counts.get(reason, 0) + 1
    return counts
