"""
Step 13 — Run receipts + retention.
Persist RunRecord with metrics, warnings, provenance, input/output hashes.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from packages.shared.models import (
    ChronologyOutput,
    EvidenceGraph,
    Metrics,
    Provenance,
    RunRecord,
    SourceDocument,
    Warning,
)


def compute_inputs_hash(source_documents: list[SourceDocument]) -> str:
    """Compute combined hash of all input document sha256 values."""
    combined = "|".join(sorted(doc.sha256 for doc in source_documents))
    return hashlib.sha256(combined.encode()).hexdigest()


def compute_outputs_hash(chronology: ChronologyOutput) -> str:
    """Compute hash of all output artifact sha256 values."""
    parts = [
        chronology.exports.pdf.sha256,
        chronology.exports.csv.sha256,
    ]
    if chronology.exports.json_export:
        parts.append(chronology.exports.json_export.sha256)
    combined = "|".join(sorted(parts))
    return hashlib.sha256(combined.encode()).hexdigest()


def create_run_record(
    run_id: str,
    started_at: datetime,
    source_documents: list[SourceDocument],
    evidence_graph: EvidenceGraph,
    chronology: ChronologyOutput,
    warnings: list[Warning],
    processing_seconds: float,
    status: str = "success",
) -> RunRecord:
    """Create a RunRecord with all metrics and provenance."""
    billing_events = [e for e in evidence_graph.events if e.event_type.value == "billing_event"]
    pt_events = [e for e in evidence_graph.events if e.event_type.value == "pt_visit"]

    metrics = Metrics(
        documents=max(len(source_documents), 1),
        pages_total=max(len(evidence_graph.pages), 1),
        pages_ocr=sum(1 for p in evidence_graph.pages if p.text_source == "ocr"),
        events_total=len(evidence_graph.events),
        events_exported=len(chronology.events_exported),
        providers_total=len(evidence_graph.providers),
        pt_events_aggregated=len(pt_events),
        billing_events_total=len(billing_events),
        processing_seconds=round(processing_seconds, 2),
    )

    provenance = Provenance(
        pipeline_version="0.1.0",
        extractor={"name": "citeline-deterministic", "version": "0.1.0"},
        ocr={"engine": "tesseract", "version": "5", "language": "en"},
        hashes={
            "inputs_sha256": compute_inputs_hash(source_documents),
            "outputs_sha256": compute_outputs_hash(chronology),
        },
    )

    return RunRecord(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        status=status,
        warnings=warnings,
        metrics=metrics,
        provenance=provenance,
    )
