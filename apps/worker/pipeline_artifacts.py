"""
Helpers for pipeline artifact bookkeeping.
"""
from __future__ import annotations

from typing import Optional

from packages.shared.artifacts import (
    ARTIFACT_BILLING_LINES_CSV,
    ARTIFACT_BILLING_LINES_JSON,
    ARTIFACT_CSV,
    ARTIFACT_DOCX,
    ARTIFACT_JSON,
    ARTIFACT_MISSING_RECORD_REQUESTS_CSV,
    ARTIFACT_MISSING_RECORD_REQUESTS_JSON,
    ARTIFACT_MISSING_RECORD_REQUESTS_MD,
    ARTIFACT_MISSING_RECORDS_CSV,
    ARTIFACT_MISSING_RECORDS_JSON,
    ARTIFACT_PDF,
    ARTIFACT_PROVIDER_DIRECTORY_CSV,
    ARTIFACT_PROVIDER_DIRECTORY_JSON,
    ARTIFACT_PARALEGAL_CHRONOLOGY_MD,
    ARTIFACT_EXTRACTION_NOTES_MD,
    ARTIFACT_PATIENT_CHRONOLOGIES_JSON,
    ARTIFACT_SPECIALS_SUMMARY_CSV,
    ARTIFACT_SPECIALS_SUMMARY_JSON,
    ARTIFACT_SPECIALS_SUMMARY_PDF,
)
from packages.shared.models import ArtifactRef, ChronologyOutput, Page, SourceDocument


def build_page_map(all_pages: list[Page], source_documents: list[SourceDocument]) -> dict[int, tuple[str, int]]:
    """
    Build page map for export provenance.
    Maps global page number -> (filename, local_page_number).
    """
    page_map: dict[int, tuple[str, int]] = {}
    doc_filename_map = {d.document_id: d.filename for d in source_documents}

    current_doc_id = None
    local_page_counter = 0
    for page in all_pages:
        if page.source_document_id != current_doc_id:
            current_doc_id = page.source_document_id
            local_page_counter = 0
        local_page_counter += 1
        page_map[page.page_number] = (
            doc_filename_map.get(page.source_document_id, "Unknown.pdf"),
            local_page_counter,
        )

    return page_map


def build_artifact_ref_entries(
    chronology: ChronologyOutput,
    prov_csv_ref: Optional[ArtifactRef],
    prov_json_ref: Optional[ArtifactRef],
    mr_csv_ref: Optional[ArtifactRef],
    mr_json_ref: Optional[ArtifactRef],
    mrr_csv_ref: Optional[ArtifactRef],
    mrr_json_ref: Optional[ArtifactRef],
    mrr_md_ref: Optional[ArtifactRef],
    bl_csv_ref: Optional[ArtifactRef],
    bl_json_ref: Optional[ArtifactRef],
    ss_csv_ref: Optional[ArtifactRef],
    ss_json_ref: Optional[ArtifactRef],
    ss_pdf_ref: Optional[ArtifactRef],
    paralegal_chronology_md_ref: Optional[ArtifactRef] = None,
    extraction_notes_md_ref: Optional[ArtifactRef] = None,
    patient_chronologies_json_ref: Optional[ArtifactRef] = None,
) -> list[tuple[str, Optional[ArtifactRef]]]:
    return [
        (ARTIFACT_PDF, chronology.exports.pdf),
        (ARTIFACT_CSV, chronology.exports.csv),
        (ARTIFACT_JSON, chronology.exports.json_export),
        (ARTIFACT_DOCX, chronology.exports.docx),
        (ARTIFACT_PROVIDER_DIRECTORY_CSV, prov_csv_ref),
        (ARTIFACT_PROVIDER_DIRECTORY_JSON, prov_json_ref),
        (ARTIFACT_MISSING_RECORDS_CSV, mr_csv_ref),
        (ARTIFACT_MISSING_RECORDS_JSON, mr_json_ref),
        (ARTIFACT_MISSING_RECORD_REQUESTS_CSV, mrr_csv_ref),
        (ARTIFACT_MISSING_RECORD_REQUESTS_JSON, mrr_json_ref),
        (ARTIFACT_MISSING_RECORD_REQUESTS_MD, mrr_md_ref),
        (ARTIFACT_BILLING_LINES_CSV, bl_csv_ref),
        (ARTIFACT_BILLING_LINES_JSON, bl_json_ref),
        (ARTIFACT_SPECIALS_SUMMARY_CSV, ss_csv_ref),
        (ARTIFACT_SPECIALS_SUMMARY_JSON, ss_json_ref),
        (ARTIFACT_SPECIALS_SUMMARY_PDF, ss_pdf_ref),
        (ARTIFACT_PARALEGAL_CHRONOLOGY_MD, paralegal_chronology_md_ref),
        (ARTIFACT_EXTRACTION_NOTES_MD, extraction_notes_md_ref),
        (ARTIFACT_PATIENT_CHRONOLOGIES_JSON, patient_chronologies_json_ref),
    ]
