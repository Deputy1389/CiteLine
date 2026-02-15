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
from packages.db.models import Artifact as ArtifactORM
from packages.db.models import Run as RunORM
from packages.db.models import SourceDocument as SourceDocORM
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
)
from apps.worker.steps.step08_citations import post_process_citations
from apps.worker.steps.step09_dedup import deduplicate_events
from apps.worker.steps.step10_confidence import apply_confidence_scoring, filter_for_export
from apps.worker.steps.step11_gaps import detect_gaps
from apps.worker.steps.step12_export import render_exports
from apps.worker.steps.step13_receipt import create_run_record

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
        providers, step_warnings = detect_providers(all_pages, all_documents)
        all_warnings.extend(step_warnings)

        # ── Step 6: Date extraction ───────────────────────────────────
        logger.info(f"[{run_id}] Step 6: Date extraction")
        dates = extract_dates_for_pages(all_pages)

        # ── Step 7: Event extraction ──────────────────────────────────
        logger.info(f"[{run_id}] Step 7: Event extraction")
        all_events = []
        all_citations = []

        clin_events, clin_cits, clin_warns = extract_clinical_events(all_pages, dates, providers)
        all_events.extend(clin_events)
        all_citations.extend(clin_cits)
        all_warnings.extend(clin_warns)

        img_events, img_cits, img_warns = extract_imaging_events(all_pages, dates, providers)
        all_events.extend(img_events)
        all_citations.extend(img_cits)
        all_warnings.extend(img_warns)

        pt_events, pt_cits, pt_warns = extract_pt_events(all_pages, dates, providers, config)
        all_events.extend(pt_events)
        all_citations.extend(pt_cits)
        all_warnings.extend(pt_warns)

        billing_events, bill_cits, bill_warns = extract_billing_events(all_pages, dates, providers)
        all_events.extend(billing_events)
        all_citations.extend(bill_cits)
        all_warnings.extend(bill_warns)

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
        )

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
        # First render exports
        chronology = render_exports(
            run_id, matter_title, export_events, gaps, providers, {}
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

                # Store artifact references
                for atype, aref in [
                    ("pdf", chronology.exports.pdf),
                    ("csv", chronology.exports.csv),
                    ("json", chronology.exports.json_export),
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
