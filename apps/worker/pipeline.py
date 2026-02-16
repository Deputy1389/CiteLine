"""
Pipeline orchestrator — runs all 14 steps in sequence.
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import datetime, timezone

from packages.db.database import get_session
from packages.db.models import (
    Page as PageORM,
    DocumentSegment as DocumentSegmentORM,
    Provider as ProviderORM,
    Event as EventORM,
    Citation as CitationORM,
    Gap as GapORM,
    Run as RunORM,
    SourceDocument as SourceDocORM,
    Artifact as ArtifactORM,
)
from packages.shared.models import (
    CaseInfo,
    ChronologyOutput,
    ChronologyResult,
    EvidenceGraph,
    EventDate,
    PipelineInputs,
    PipelineOutputs,
    RunConfig,
    SourceDocument,
    Warning,
)
from packages.shared.schema_validator import validate_output
from packages.shared.storage import get_upload_path, sha256_bytes

from apps.worker.steps.step00_validate import validate_inputs
from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step02_text_acquire import acquire_text
from apps.worker.steps.step03_classify import classify_pages
from apps.worker.steps.step04_segment import segment_documents
from apps.worker.steps.step05_provider import detect_providers
from apps.worker.steps.step06_dates import extract_dates_for_pages
from apps.worker.steps.step07_events import (
    extract_billing_events,
    extract_clinical_events,
    extract_imaging_events,
    extract_pt_events,
    extract_lab_events,
    extract_discharge_events,
    extract_operative_events,
)

from apps.worker.steps.step08_citations import post_process_citations
from apps.worker.steps.step09_dedup import deduplicate_events
from apps.worker.steps.step10_confidence import apply_confidence_scoring, filter_for_export
from apps.worker.steps.step11_gaps import detect_gaps
from apps.worker.steps.step12_export import render_exports
from apps.worker.steps.step13_receipt import create_run_record
from apps.worker.lib.provider_normalize import normalize_provider_entities, compute_coverage_spans
from apps.worker.steps.step14_provider_directory import render_provider_directory
from apps.worker.steps.step15_missing_records import detect_missing_records, render_missing_records
from apps.worker.steps.step16_billing_lines import extract_billing_lines, render_billing_lines
from apps.worker.steps.step17_specials_summary import compute_specials_summary, render_specials_summary

logger = logging.getLogger(__name__)


def run_pipeline(run_id: str) -> None:
    """
    Execute the full extraction pipeline for a given run.
    Updates the Run record in the database with results.
    """
    started_at = datetime.now(timezone.utc)
    start_time = time.time()
    all_warnings: list[Warning] = []

    try:
        # ── Load run from DB ──────────────────────────────────────────
        with get_session() as session:
            run_row = session.query(RunORM).filter_by(id=run_id).first()
            if not run_row:
                logger.error(f"Run {run_id} not found")
                return

            run_row.status = "running"
            run_row.started_at = started_at
            session.flush()

            matter = run_row.matter
            matter_title = matter.title
            matter_id = matter.id
            firm_id = matter.firm_id
            tz = matter.timezone or "America/Los_Angeles"

            config = RunConfig(**json.loads(run_row.config_json)) if run_row.config_json else RunConfig()

            # Load source documents
            doc_rows = session.query(SourceDocORM).filter_by(matter_id=matter_id).all()
            source_documents = [
                SourceDocument(
                    document_id=d.id,
                    filename=d.filename,
                    mime_type=d.mime_type,
                    sha256=d.sha256,
                    bytes=d.bytes,
                    uploaded_at=d.uploaded_at,
                )
                for d in doc_rows
            ]

        if not source_documents:
            _fail_run(run_id, "No source documents found for this matter")
            return

        # ── Step 0: Validate ──────────────────────────────────────────
        logger.info(f"[{run_id}] Step 0: Input validation")
        valid_docs, step_warnings = validate_inputs(source_documents, config)
        all_warnings.extend(step_warnings)
        if not valid_docs:
            _fail_run(run_id, "No valid documents after validation")
            return

        # ── Step 1-2: Page split + text acquisition ───────────────────
        all_pages = []
        total_ocr = 0
        page_offset = 0

        for doc in valid_docs:
            pdf_path = str(get_upload_path(doc.document_id))
            logger.info(f"[{run_id}] Step 1: Splitting pages for {doc.document_id}")
            pages, step_warnings = split_pages(
                pdf_path, doc.document_id, page_offset, config.max_pages - page_offset
            )
            all_warnings.extend(step_warnings)

            logger.info(f"[{run_id}] Step 2: Text acquisition for {doc.document_id}")
            pages, ocr_count, step_warnings = acquire_text(pages, pdf_path)
            all_warnings.extend(step_warnings)
            total_ocr += ocr_count

            all_pages.extend(pages)
            page_offset += len(pages)

        if not all_pages:
            _fail_run(run_id, "No pages extracted from any document")
            return

        # ── Step 3: Classify pages ────────────────────────────────────
        logger.info(f"[{run_id}] Step 3: Page classification")
        all_pages, step_warnings = classify_pages(all_pages)
        all_warnings.extend(step_warnings)

        # ── Step 4: Document segmentation ─────────────────────────────
        logger.info(f"[{run_id}] Step 4: Document segmentation")
        all_documents = []
        for doc in valid_docs:
            doc_pages = [p for p in all_pages if p.source_document_id == doc.document_id]
            docs, step_warnings = segment_documents(doc_pages, doc.document_id)
            all_warnings.extend(step_warnings)
            all_documents.extend(docs)

        # ── Step 5: Provider detection ────────────────────────────────
        logger.info(f"[{run_id}] Step 5: Provider detection")
        providers, page_provider_map, step_warnings = detect_providers(all_pages, all_documents)
        all_warnings.extend(step_warnings)

        # ── Step 6: Date extraction ───────────────────────────────────
        logger.info(f"[{run_id}] Step 6: Date extraction")
        dates = extract_dates_for_pages(all_pages)

        # ── Step 7: Event extraction ──────────────────────────────────
        logger.info(f"[{run_id}] Step 7: Event extraction")
        all_events = []
        all_citations = []
        all_skipped = []

        clin_events, clin_cits, clin_warns, clin_skipped = extract_clinical_events(all_pages, dates, providers, page_provider_map)
        all_events.extend(clin_events)
        all_citations.extend(clin_cits)
        all_warnings.extend(clin_warns)
        all_skipped.extend(clin_skipped)

        img_events, img_cits, img_warns, img_skipped = extract_imaging_events(all_pages, dates, providers, page_provider_map)
        all_events.extend(img_events)
        all_citations.extend(img_cits)
        all_warnings.extend(img_warns)
        all_skipped.extend(img_skipped)

        pt_events, pt_cits, pt_warns, pt_skipped = extract_pt_events(all_pages, dates, providers, config, page_provider_map)
        all_events.extend(pt_events)
        all_citations.extend(pt_cits)
        all_warnings.extend(pt_warns)
        all_skipped.extend(pt_skipped)

        billing_events, bill_cits, bill_warns, bill_skipped = extract_billing_events(all_pages, dates, providers, page_provider_map)
        all_events.extend(billing_events)
        all_citations.extend(bill_cits)
        all_warnings.extend(bill_warns)
        all_skipped.extend(bill_skipped)

        lab_events, lab_cits, lab_warns, lab_skipped = extract_lab_events(all_pages, dates, providers, page_provider_map)
        all_events.extend(lab_events)
        all_citations.extend(lab_cits)
        all_warnings.extend(lab_warns)
        all_skipped.extend(lab_skipped)

        ds_events, ds_cits, ds_warns, ds_skipped = extract_discharge_events(all_pages, dates, providers, page_provider_map)
        all_events.extend(ds_events)
        all_citations.extend(ds_cits)
        all_warnings.extend(ds_warns)
        all_skipped.extend(ds_skipped)

        op_events, op_cits, op_warns, op_skipped = extract_operative_events(all_pages, dates, providers, page_provider_map)
        all_events.extend(op_events)
        all_citations.extend(op_cits)
        all_warnings.extend(op_warns)
        all_skipped.extend(op_skipped)

        # ── Step 8: Citation post-processing ──────────────────────────
        logger.info(f"[{run_id}] Step 8: Citation capture")
        all_citations, step_warnings = post_process_citations(all_citations)
        all_warnings.extend(step_warnings)

        # ── Step 9: Deduplication ─────────────────────────────────────
        logger.info(f"[{run_id}] Step 9: Deduplication")
        all_events, step_warnings = deduplicate_events(all_events)
        all_warnings.extend(step_warnings)

        # ── Step 10: Confidence scoring ───────────────────────────────
        logger.info(f"[{run_id}] Step 10: Confidence scoring")
        all_events, step_warnings = apply_confidence_scoring(all_events, config)
        all_warnings.extend(step_warnings)

        export_events = filter_for_export(all_events, config)

        # ── Step 11: Gap detection ────────────────────────────────────
        logger.info(f"[{run_id}] Step 11: Gap detection")
        export_events, gaps, step_warnings = detect_gaps(export_events, config)
        all_warnings.extend(step_warnings)

        # Build evidence graph
        evidence_graph = EvidenceGraph(
            documents=all_documents,
            pages=all_pages,
            providers=providers,
            events=all_events,
            citations=all_citations,
            gaps=gaps,
            skipped_events=all_skipped,
        )

        # ── Extraction metrics ─────────────────────────────────────────
        page_type_counts: dict[str, int] = {}
        for p in all_pages:
            pt = (p.page_type or "other").value if hasattr(p.page_type, "value") else str(p.page_type or "other")
            page_type_counts[pt] = page_type_counts.get(pt, 0) + 1

        event_type_counts: dict[str, int] = {}
        for e in all_events:
            et = e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)
            event_type_counts[et] = event_type_counts.get(et, 0) + 1

        evidence_graph.extensions["extraction_metrics"] = {
            "pages_total": len(all_pages),
            "pages_classified": page_type_counts,
            "providers_detected": len(providers),
            "events_total": len(all_events),
            "events_by_type": event_type_counts,
            "events_with_date": sum(1 for e in all_events if e.date),
            "events_dateless": sum(1 for e in all_events if not e.date),
            "events_low_confidence": sum(1 for e in all_events if e.confidence < config.event_confidence_min_export),
            "events_exported": len(export_events),
            "skipped_events": len(all_skipped),
            "facts_total": sum(len(e.facts) for e in all_events),
            "citations_total": len(all_citations),
        }
        logger.info(f"[{run_id}] Extraction metrics: {evidence_graph.extensions['extraction_metrics']}")
        # ── Step 14a: Provider normalization + coverage ────────────────
        logger.info(f"[{run_id}] Step 14a: Provider normalization")
        providers_normalized = normalize_provider_entities(evidence_graph)
        coverage_spans = compute_coverage_spans(providers_normalized)
        evidence_graph.extensions["providers_normalized"] = providers_normalized
        evidence_graph.extensions["coverage_spans"] = coverage_spans

        # ── Step 14b: Provider directory artifact ──────────────────────
        logger.info(f"[{run_id}] Step 14b: Provider directory artifact")
        prov_csv_ref, prov_json_ref = render_provider_directory(run_id, providers_normalized)

        # ── Step 15: Missing record detection ─────────────────────────
        logger.info(f"[{run_id}] Step 15: Missing record detection")
        missing_records_payload = detect_missing_records(evidence_graph, providers_normalized)
        evidence_graph.extensions["missing_records"] = missing_records_payload
        mr_csv_ref, mr_json_ref = render_missing_records(run_id, missing_records_payload)

        # ── Step 16: Billing lines extraction ─────────────────────────
        logger.info(f"[{run_id}] Step 16: Billing lines extraction")
        billing_lines_payload = extract_billing_lines(evidence_graph, providers_normalized)
        evidence_graph.extensions["billing_lines"] = billing_lines_payload
        bl_csv_ref, bl_json_ref = render_billing_lines(run_id, billing_lines_payload)

        # ── Step 17: Specials summary ─────────────────────────────────
        logger.info(f"[{run_id}] Step 17: Specials summary")
        specials_payload = compute_specials_summary(billing_lines_payload, providers_normalized)
        evidence_graph.extensions["specials_summary"] = specials_payload
        ss_csv_ref, ss_json_ref, ss_pdf_ref = render_specials_summary(run_id, specials_payload, matter_title)

        # ── Step 12: Export rendering ─────────────────────────────────
        logger.info(f"[{run_id}] Step 12: Export rendering")
        processing_seconds = time.time() - start_time

        # Build full output for JSON export
        case_info = CaseInfo(
            case_id=matter_id,
            firm_id=firm_id,
            title=matter_title,
            timezone=tz,
        )

        # Temporary chronology output (will be replaced after rendering)
        # Build page map for explicit provenance in exports
        page_map: dict[int, tuple[str, int]] = {}
        doc_filename_map = {d.document_id: d.filename for d in source_documents}
        
        # We assume all_pages is ordered by document as constructed in Steps 1-2
        # Use a robust way: group pages by doc_id, sort, then assign local numbers?
        # Or simplistic iteration if we trust the order?
        # Trusting order is fine for now, but let's be robust against non-contiguous pages if that ever happens.
        # Actually, split_pages returns sequential pages. pipeline appends them.
        # So simplistic iteration with doc_id check is fine.
        
        # Reset per document
        _current_doc_id = None
        _local_page_counter = 0
        
        # Sort all_pages by page_number just in case? 
        # They should be sorted by global page number already.
        for p in all_pages:
            if p.source_document_id != _current_doc_id:
                _current_doc_id = p.source_document_id
                _local_page_counter = 0
            _local_page_counter += 1
            
            fname = doc_filename_map.get(p.source_document_id, "Unknown.pdf")
            page_map[p.page_number] = (fname, _local_page_counter)

        # First render exports
        chronology = render_exports(
            run_id, matter_title, export_events, gaps, providers,
            page_map=page_map,
        )

        # ── Step 13: Run receipt ──────────────────────────────────────
        logger.info(f"[{run_id}] Step 13: Run receipt")
        run_record = create_run_record(
            run_id, started_at, source_documents, evidence_graph,
            chronology, all_warnings, processing_seconds,
        )

        # Now build the full result and re-export JSON with complete data
        full_result = ChronologyResult(
            schema_version="0.1.0",
            generated_at=datetime.now(timezone.utc),
            case=case_info,
            inputs=PipelineInputs(
                source_documents=source_documents,
                run_config=config,
            ),
            outputs=PipelineOutputs(
                run=run_record,
                evidence_graph=evidence_graph,
                chronology=chronology,
            ),
        )

        # Re-export JSON with full data
        full_output_dict = json.loads(full_result.model_dump_json())
        from packages.shared.storage import save_artifact
        import hashlib
        json_bytes = json.dumps(full_output_dict, indent=2, default=str).encode()
        json_path = save_artifact(run_id, "evidence_graph.json", json_bytes)
        json_sha = hashlib.sha256(json_bytes).hexdigest()
        if chronology.exports.json_export is None:
            from packages.shared.models import ArtifactRef
            chronology.exports.json_export = ArtifactRef(
                uri=str(json_path),
                sha256=json_sha,
                bytes=len(json_bytes),
            )
        else:
            chronology.exports.json_export.uri = str(json_path)
            chronology.exports.json_export.sha256 = json_sha
            chronology.exports.json_export.bytes = len(json_bytes)

        # Validate against schema
        is_valid, errors = validate_output(full_output_dict)
        status = "success" if is_valid else "partial"
        if not is_valid:
            for err in errors[:10]:
                all_warnings.append(Warning(
                    code="SCHEMA_VALIDATION_ERROR",
                    message=err[:500],
                ))
            logger.warning(f"[{run_id}] Schema validation failed with {len(errors)} errors")

        # ── Persist results ───────────────────────────────────────────
        with get_session() as session:
            run_row = session.query(RunORM).filter_by(id=run_id).first()
            if run_row:
                run_row.status = status
                run_row.finished_at = datetime.now(timezone.utc)
                run_row.processing_seconds = processing_seconds
                run_row.metrics_json = run_record.metrics.model_dump_json()
                run_row.warnings_json = json.dumps([w.model_dump() for w in all_warnings])
                run_row.provenance_json = run_record.provenance.model_dump_json()

                # ── Idempotency: Clear existing data ──────────────────
                # Clear all related tables to prevent duplicates on retry
                session.query(PageORM).filter_by(run_id=run_id).delete()
                session.query(DocumentSegmentORM).filter_by(run_id=run_id).delete()
                session.query(ProviderORM).filter_by(run_id=run_id).delete()
                session.query(EventORM).filter_by(run_id=run_id).delete()
                session.query(CitationORM).filter_by(run_id=run_id).delete()
                session.query(GapORM).filter_by(run_id=run_id).delete()
                session.query(ArtifactORM).filter_by(run_id=run_id).delete()
                session.flush()

                # ── Persist Evidence Graph ────────────────────────────
                # 1. Pages
                for page in evidence_graph.pages:
                    p_orm = PageORM(
                        id=page.page_id,
                        run_id=run_id,
                        source_document_id=page.source_document_id,
                        page_number=page.page_number,
                        text=page.text,
                        text_source=page.text_source,
                        page_type=page.page_type.value if page.page_type else None,
                        layout_json=page.layout.model_dump(mode='json') if page.layout else None,
                    )
                    session.add(p_orm)

                # 2. Document Segments
                for doc in evidence_graph.documents:
                    seg_orm = DocumentSegmentORM(
                        id=doc.document_id,
                        run_id=run_id,
                        source_document_id=doc.source_document_id,
                        page_start=doc.page_start,
                        page_end=doc.page_end,
                        page_types_json=[pt.model_dump(mode='json') for pt in doc.page_types],
                        declared_document_type=doc.declared_document_type.value if doc.declared_document_type else None,
                        confidence=doc.confidence,
                    )
                    session.add(seg_orm)

                # 3. Providers
                for prov in evidence_graph.providers:
                    prov_orm = ProviderORM(
                        id=prov.provider_id,
                        run_id=run_id,
                        detected_name_raw=prov.detected_name_raw,
                        normalized_name=prov.normalized_name,
                        provider_type=prov.provider_type.value,
                        confidence=prov.confidence,
                        evidence_json=[e.model_dump(mode='json') for e in prov.evidence],
                    )
                    session.add(prov_orm)

                # 4. Citations
                for cit in evidence_graph.citations:
                    cit_orm = CitationORM(
                        id=cit.citation_id,
                        run_id=run_id,
                        source_document_id=cit.source_document_id,
                        page_number=cit.page_number,
                        snippet=cit.snippet,
                        bbox_json=cit.bbox.model_dump(mode='json'),
                        text_hash=cit.text_hash,
                    )
                    session.add(cit_orm)

                # 5. Events
                for evt in evidence_graph.events:
                    # Handle provider_id FK
                    pid = evt.provider_id
                    if pid == "unknown" or not pid:
                        pid_fk = None
                    else:
                        pid_fk = pid
                    
                    evt_orm = EventORM(
                        id=evt.event_id,
                        run_id=run_id,
                        provider_id=pid_fk,
                        event_type=evt.event_type.value,
                        date_json=evt.date.model_dump(mode='json') if evt.date else None,
                        encounter_type_raw=evt.encounter_type_raw,
                        facts_json=[f.model_dump(mode='json') for f in evt.facts],
                        diagnoses_json=[d.model_dump(mode='json') for d in evt.diagnoses],
                        procedures_json=[p.model_dump(mode='json') for p in evt.procedures],
                        imaging_json=evt.imaging.model_dump(mode='json') if evt.imaging else None,
                        billing_json=evt.billing.model_dump(mode='json') if evt.billing else None,
                        confidence=evt.confidence,
                        flags_json=evt.flags,
                        citation_ids_json=evt.citation_ids,
                        source_page_numbers_json=evt.source_page_numbers,
                    )
                    session.add(evt_orm)

                # 6. Gaps
                for gap in evidence_graph.gaps:
                    gap_orm = GapORM(
                        id=gap.gap_id,
                        run_id=run_id,
                        start_date=gap.start_date.isoformat(), # Stored as string in DB for now? or Date? Model says String(20)
                        end_date=gap.end_date.isoformat(),
                        duration_days=gap.duration_days,
                        threshold_days=gap.threshold_days,
                        confidence=gap.confidence,
                        related_event_ids_json=gap.related_event_ids,
                    )
                    session.add(gap_orm)

                # Store artifact references
                for atype, aref in [
                    ("pdf", chronology.exports.pdf),
                    ("csv", chronology.exports.csv),
                    ("json", chronology.exports.json_export),
                    ("provider_directory_csv", prov_csv_ref),
                    ("provider_directory_json", prov_json_ref),
                    ("missing_records_csv", mr_csv_ref),
                    ("missing_records_json", mr_json_ref),
                    ("billing_lines_csv", bl_csv_ref),
                    ("billing_lines_json", bl_json_ref),
                    ("specials_summary_csv", ss_csv_ref),
                    ("specials_summary_json", ss_json_ref),
                ]:
                    if aref:
                        artifact = ArtifactORM(
                            run_id=run_id,
                            artifact_type=atype,
                            storage_uri=aref.uri,
                            sha256=aref.sha256,
                            bytes=aref.bytes,
                        )
                        session.add(artifact)

        logger.info(f"[{run_id}] Pipeline completed: status={status}, events={len(all_events)}, exported={len(export_events)}")

    except Exception as exc:
        logger.exception(f"[{run_id}] Pipeline failed: {exc}")
        _fail_run(run_id, str(exc))


def _fail_run(run_id: str, error: str) -> None:
    """Mark a run as failed."""
    with get_session() as session:
        run_row = session.query(RunORM).filter_by(id=run_id).first()
        if run_row:
            run_row.status = "failed"
            run_row.finished_at = datetime.now(timezone.utc)
            run_row.error_message = error[:2000]
