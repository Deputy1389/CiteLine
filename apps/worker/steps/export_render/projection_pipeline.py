"""
Internal pipeline for projection-based chronology export.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from apps.worker.project.models import ChronologyProjection
from apps.worker.steps.export_render.common import parse_date_string

if TYPE_CHECKING:
    from datetime import date
    from packages.shared.models import Event, Provider


def prepare_projection_bundle(
    events: list[Event],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None,
    page_text_by_number: dict[int, str] | None,
    narrative_synthesis: str | None,
    missing_records_payload: dict | None,
    build_chronology_projection: Callable,
    infer_page_patient_labels: Callable,
    enrich_projection_procedure_entries: Callable,
    ensure_mri_bucket_entry: Callable,
    ensure_procedure_bucket_entry: Callable,
    ensure_ortho_bucket_entry: Callable,
    normalize_projection_patient_labels: Callable,
    merge_projection_entries_same_day: Callable,
    compute_care_window_from_projection: Callable,
    apply_claim_guard_to_narrative: Callable,
    repair_case_summary_narrative: Callable,
) -> dict[str, Any]:
    """
    Common logic to prepare the projection, apply enrichments, and compute metadata.
    """
    page_patient_labels = infer_page_patient_labels(page_text_by_number)
    
    selection_meta: dict[str, Any] = {}
    projection_debug_sink: list[dict[str, Any]] = []
    projection = build_chronology_projection(
        events=events,
        providers=providers,
        page_map=page_map,
        page_patient_labels=page_patient_labels,
        page_text_by_number=page_text_by_number,
        debug_sink=projection_debug_sink,
        selection_meta=selection_meta,
    )
    appendix_projection = projection.model_copy()
    
    projection = enrich_projection_procedure_entries(
        projection, 
        page_text_by_number=page_text_by_number, 
        page_map=page_map
    )
    projection = ensure_mri_bucket_entry(
        projection, 
        page_text_by_number=page_text_by_number, 
        page_map=page_map
    )
    projection = ensure_procedure_bucket_entry(
        projection, 
        page_text_by_number=page_text_by_number, 
        page_map=page_map
    )
    projection = ensure_ortho_bucket_entry(
        projection, 
        page_text_by_number=page_text_by_number, 
        page_map=page_map,
        raw_events=events
    )
    
    projection = normalize_projection_patient_labels(projection)
    projection = merge_projection_entries_same_day(projection)
    care_window = compute_care_window_from_projection(projection)
    
    claim_guard_report = {}
    if narrative_synthesis:
        narrative_synthesis, claim_guard_report = apply_claim_guard_to_narrative(
            narrative_synthesis,
            page_text_by_number,
        )
        narrative_synthesis = repair_case_summary_narrative(
            narrative_synthesis,
            page_text_by_number=page_text_by_number,
            page_map=page_map,
            care_window_start=care_window[0] if care_window else None,
            care_window_end=care_window[1] if care_window else None,
            projection_entries=projection.entries,
        )

    return {
        "projection": projection,
        "appendix_projection": appendix_projection,
        "care_window": care_window,
        "narrative_synthesis": narrative_synthesis,
        "claim_guard_report": claim_guard_report,
        "projection_debug": projection_debug_sink,
        "selection_meta": selection_meta,
    }


def build_selection_debug_payload(
    selection_meta: dict,
    events: list[Event],
    projection_debug: dict,
) -> dict:
    stopping_reason = str(selection_meta.get("stopping_reason") or "unknown")
    payload = {
        "version": "1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stopping_reason": stopping_reason,
        "selection_criteria": selection_meta,
        "total_events_in": len(events),
        "projection_debug": projection_debug,
    }
    return payload
