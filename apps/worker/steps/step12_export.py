"""
Export step for Citeline (Step 12).
Thin wrapper over modularized components in export_render/.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.worker.steps.export_render import (
    orchestrator,
    orchestrator_utils,
    common,
    medication_utils,
    extraction_utils,
    gap_utils,
    timeline_pdf,
    csv_render,
    docx_render,
    projection_enrichment,
)

if TYPE_CHECKING:
    from packages.shared.models import CaseInfo, Citation, Event, Gap, Provider, ChronologyOutput, ArtifactRef


def render_exports(*args, **kwargs) -> ChronologyOutput:
    return orchestrator.render_exports(*args, **kwargs)


def render_patient_chronology_reports(*args, **kwargs) -> ArtifactRef | None:
    return orchestrator.render_patient_chronology_reports(*args, **kwargs)


def generate_docx(*args, **kwargs) -> bytes:
    return docx_render.generate_docx(*args, **kwargs)


def generate_pdf(*args, **kwargs) -> bytes:
    return timeline_pdf.generate_pdf(*args, **kwargs)


def generate_pdf_from_projection(*args, **kwargs) -> bytes:
    return timeline_pdf.generate_pdf_from_projection(*args, **kwargs)


def generate_csv(*args, **kwargs) -> bytes:
    # unit tests expect generate_csv(events, providers, page_map) but CSV now typically uses projection
    # we'll delegate to a compatibility shim if needed or just orchestrate a quick projection
    from apps.worker.project.chronology import build_chronology_projection
    from apps.worker.project.models import ChronologyProjection
    from datetime import datetime, timezone
    
    # If the first arg is already a projection, use it directly
    if args and hasattr(args[0], 'entries'):
        return csv_render.generate_csv_from_projection(args[0])
    
    # Otherwise build a quick projection for compatibility
    events = args[0] if len(args) > 0 else []
    providers = args[1] if len(args) > 1 else []
    page_map = args[2] if len(args) > 2 else None
    
    proj = build_chronology_projection(events, providers, page_map=page_map)
    return csv_render.generate_csv_from_projection(proj)


def _enrich_projection_procedure_entries(*args, **kwargs):
    return projection_enrichment._enrich_projection_procedure_entries(*args, **kwargs)


def _ensure_procedure_bucket_entry(*args, **kwargs):
    return projection_enrichment._ensure_procedure_bucket_entry(*args, **kwargs)


def _ensure_mri_bucket_entry(*args, **kwargs):
    return projection_enrichment._ensure_mri_bucket_entry(*args, **kwargs)


def _ensure_ortho_bucket_entry(*args, **kwargs):
    return projection_enrichment._ensure_ortho_bucket_entry(*args, **kwargs)


def _normalize_projection_patient_labels(*args, **kwargs):
    return orchestrator_utils._normalize_projection_patient_labels(*args, **kwargs)


# Backward compatibility wrappers for internal helpers
def _date_str(event: Event) -> str:
    return common._date_str(event)


def _provider_name(event: Event, providers: list[Provider]) -> str:
    return common._provider_name(event, providers)


def _facts_text(event: Event) -> str:
    return common._facts_text(event)


def _clean_narrative_text(text: str | None) -> str:
    return common._clean_narrative_text(text)


def _clean_direct_snippet(text: str) -> str:
    return common._clean_direct_snippet(text)


def _sanitize_filename_display(fname: str) -> str:
    return common._sanitize_filename_display(fname)


def _sanitize_citation_display(citation: str) -> str:
    return common._sanitize_citation_display(citation)


def _has_inpatient_markers(event_type_display: str, facts: list[str]) -> bool:
    return common._has_inpatient_markers(event_type_display, facts)


def _normalized_encounter_label(entry) -> str:
    return common._normalized_encounter_label(entry)


def _appendix_dx_line_ok(text: str) -> bool:
    return common._appendix_dx_line_ok(text)


def _appendix_dx_line_generic(text: str) -> bool:
    return common._appendix_dx_line_generic(text)


def _is_sdoh_noise(text: str) -> bool:
    return common._is_sdoh_noise(text)


def _is_meta_language(text: str) -> bool:
    return common._is_meta_language(text)


def parse_date_string(date_str: str | None) -> Any:
    return common.parse_date_string(date_str)


def _sanitize_top10_sentence(text: str) -> str:
    return common._sanitize_top10_sentence(text)


def _sanitize_render_sentence(text: str) -> str:
    return common._sanitize_render_sentence(text)


def _extract_med_mentions(text: str) -> list[dict]:
    return medication_utils._extract_med_mentions(text)


def _extract_medication_changes(entries: list) -> list[str]:
    return medication_utils._extract_medication_changes(entries)


def _extract_medication_change_rows(entries: list) -> list[dict]:
    return medication_utils._extract_medication_change_rows(entries)


def _extract_diagnosis_items(entries: list) -> list[str]:
    return extraction_utils._extract_diagnosis_items(entries)


def _extract_pro_items(entries: list) -> list[str]:
    return extraction_utils._extract_pro_items(entries)


def _extract_sdoh_items(entries: list) -> list[str]:
    return extraction_utils._extract_sdoh_items(entries)


def _contradiction_flags(entries: list) -> list[str]:
    return extraction_utils._contradiction_flags(entries)


def _material_gap_rows(gap_list: list[Gap], entries_by_patient: dict[str, list], raw_event_by_id: dict[str, Event], page_map=None) -> list[dict]:
    return gap_utils._material_gap_rows(gap_list, entries_by_patient, raw_event_by_id, page_map)


def _extract_disposition(facts: Any) -> str | None:
    return common._extract_disposition(facts)


def _pages_ref(event: Event, page_map: dict[int, tuple[str, int]] | None = None) -> str:
    return common._pages_ref(event, page_map)


def _slugify(value: str) -> str:
    return common._slugify(value)


def _pick_theory_entry(*args, **kwargs):
    return common._pick_theory_entry(*args, **kwargs)


def _fact_excerpt(*args, **kwargs):
    return common._fact_excerpt(*args, **kwargs)


def _set_cell_shading(cell, hex_color: str):
    return common._set_cell_shading(cell, hex_color)


def _projection_entry_substance_score(entry) -> int:
    return common._projection_entry_substance_score(entry)


def _repair_case_summary_narrative(*args, **kwargs) -> str | None:
    return extraction_utils._repair_case_summary_narrative(*args, **kwargs)


def generate_executive_summary(events: list[Event], matter_title: str, case_info: CaseInfo | None = None) -> str:
    return timeline_pdf.generate_executive_summary(events, matter_title, case_info)
