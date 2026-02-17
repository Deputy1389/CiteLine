"""
Persistence helpers for pipeline run outputs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from packages.db.database import get_session
from packages.db.models import (
    Artifact as ArtifactORM,
    Citation as CitationORM,
    DocumentSegment as DocumentSegmentORM,
    Event as EventORM,
    Gap as GapORM,
    Page as PageORM,
    Provider as ProviderORM,
    Run as RunORM,
)
from packages.shared.models import ArtifactRef, EvidenceGraph, RunRecord, Warning


def persist_pipeline_state(
    run_id: str,
    status: str,
    processing_seconds: float,
    run_record: RunRecord,
    all_warnings: list[Warning],
    evidence_graph: EvidenceGraph,
    artifact_entries: list[tuple[str, Optional[ArtifactRef]]],
) -> None:
    with get_session() as session:
        run_row = session.query(RunORM).filter_by(id=run_id).first()
        if not run_row:
            return

        run_row.status = status
        run_row.finished_at = datetime.now(timezone.utc)
        run_row.processing_seconds = processing_seconds
        run_row.metrics_json = run_record.metrics.model_dump_json()
        run_row.warnings_json = json.dumps([w.model_dump() for w in all_warnings])
        run_row.provenance_json = run_record.provenance.model_dump_json()

        # Idempotency: clear prior rows for this run.
        session.query(PageORM).filter_by(run_id=run_id).delete()
        session.query(DocumentSegmentORM).filter_by(run_id=run_id).delete()
        session.query(ProviderORM).filter_by(run_id=run_id).delete()
        session.query(EventORM).filter_by(run_id=run_id).delete()
        session.query(CitationORM).filter_by(run_id=run_id).delete()
        session.query(GapORM).filter_by(run_id=run_id).delete()
        session.query(ArtifactORM).filter_by(run_id=run_id).delete()
        session.flush()

        for page in evidence_graph.pages:
            session.add(PageORM(
                id=page.page_id,
                run_id=run_id,
                source_document_id=page.source_document_id,
                page_number=page.page_number,
                text=page.text,
                text_source=page.text_source,
                page_type=page.page_type.value if page.page_type else None,
                layout_json=page.layout.model_dump(mode="json") if page.layout else None,
            ))

        for doc in evidence_graph.documents:
            session.add(DocumentSegmentORM(
                id=doc.document_id,
                run_id=run_id,
                source_document_id=doc.source_document_id,
                page_start=doc.page_start,
                page_end=doc.page_end,
                page_types_json=[pt.model_dump(mode="json") for pt in doc.page_types],
                declared_document_type=doc.declared_document_type.value if doc.declared_document_type else None,
                confidence=doc.confidence,
            ))

        for prov in evidence_graph.providers:
            session.add(ProviderORM(
                id=prov.provider_id,
                run_id=run_id,
                detected_name_raw=prov.detected_name_raw,
                normalized_name=prov.normalized_name,
                provider_type=prov.provider_type.value,
                confidence=prov.confidence,
                evidence_json=[e.model_dump(mode="json") for e in prov.evidence],
            ))

        for cit in evidence_graph.citations:
            session.add(CitationORM(
                id=cit.citation_id,
                run_id=run_id,
                source_document_id=cit.source_document_id,
                page_number=cit.page_number,
                snippet=cit.snippet,
                bbox_json=cit.bbox.model_dump(mode="json"),
                text_hash=cit.text_hash,
            ))

        for evt in evidence_graph.events:
            pid_fk = evt.provider_id if evt.provider_id and evt.provider_id != "unknown" else None
            session.add(EventORM(
                id=evt.event_id,
                run_id=run_id,
                provider_id=pid_fk,
                event_type=evt.event_type.value,
                date_json=evt.date.model_dump(mode="json") if evt.date else None,
                encounter_type_raw=evt.encounter_type_raw,
                facts_json=[f.model_dump(mode="json") for f in evt.facts],
                diagnoses_json=[d.model_dump(mode="json") for d in evt.diagnoses],
                procedures_json=[p.model_dump(mode="json") for p in evt.procedures],
                imaging_json=evt.imaging.model_dump(mode="json") if evt.imaging else None,
                billing_json=evt.billing.model_dump(mode="json") if evt.billing else None,
                confidence=evt.confidence,
                flags_json=evt.flags,
                citation_ids_json=evt.citation_ids,
                source_page_numbers_json=evt.source_page_numbers,
                extensions_json=evt.extensions,
            ))

        for gap in evidence_graph.gaps:
            session.add(GapORM(
                id=gap.gap_id,
                run_id=run_id,
                start_date=gap.start_date.isoformat(),
                end_date=gap.end_date.isoformat(),
                duration_days=gap.duration_days,
                threshold_days=gap.threshold_days,
                confidence=gap.confidence,
                related_event_ids_json=gap.related_event_ids,
            ))

        for atype, aref in artifact_entries:
            if aref:
                session.add(ArtifactORM(
                    run_id=run_id,
                    artifact_type=atype,
                    storage_uri=aref.uri,
                    sha256=aref.sha256,
                    bytes=aref.bytes,
                ))
