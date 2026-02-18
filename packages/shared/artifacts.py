"""
Central artifact registry for worker, API, and tests.
"""
from __future__ import annotations

from collections.abc import Iterable

# Core chronology exports
ARTIFACT_PDF = "pdf"
ARTIFACT_CSV = "csv"
ARTIFACT_JSON = "json"
ARTIFACT_DOCX = "docx"

# Extension artifacts
ARTIFACT_PROVIDER_DIRECTORY_CSV = "provider_directory_csv"
ARTIFACT_PROVIDER_DIRECTORY_JSON = "provider_directory_json"
ARTIFACT_MISSING_RECORDS_CSV = "missing_records_csv"
ARTIFACT_MISSING_RECORDS_JSON = "missing_records_json"
ARTIFACT_MISSING_RECORD_REQUESTS_CSV = "missing_record_requests_csv"
ARTIFACT_MISSING_RECORD_REQUESTS_JSON = "missing_record_requests_json"
ARTIFACT_MISSING_RECORD_REQUESTS_MD = "missing_record_requests_md"
ARTIFACT_BILLING_LINES_CSV = "billing_lines_csv"
ARTIFACT_BILLING_LINES_JSON = "billing_lines_json"
ARTIFACT_SPECIALS_SUMMARY_CSV = "specials_summary_csv"
ARTIFACT_SPECIALS_SUMMARY_JSON = "specials_summary_json"
ARTIFACT_SPECIALS_SUMMARY_PDF = "specials_summary_pdf"
ARTIFACT_PARALEGAL_CHRONOLOGY_MD = "paralegal_chronology_md"
ARTIFACT_EXTRACTION_NOTES_MD = "extraction_notes_md"
ARTIFACT_PATIENT_CHRONOLOGIES_JSON = "patient_chronologies_json"


ARTIFACT_EXTENSION_MAP: dict[str, str] = {
    ARTIFACT_PDF: "pdf",
    ARTIFACT_CSV: "csv",
    ARTIFACT_JSON: "json",
    ARTIFACT_DOCX: "docx",
    ARTIFACT_PROVIDER_DIRECTORY_CSV: "csv",
    ARTIFACT_PROVIDER_DIRECTORY_JSON: "json",
    ARTIFACT_MISSING_RECORDS_CSV: "csv",
    ARTIFACT_MISSING_RECORDS_JSON: "json",
    ARTIFACT_MISSING_RECORD_REQUESTS_CSV: "csv",
    ARTIFACT_MISSING_RECORD_REQUESTS_JSON: "json",
    ARTIFACT_MISSING_RECORD_REQUESTS_MD: "md",
    ARTIFACT_BILLING_LINES_CSV: "csv",
    ARTIFACT_BILLING_LINES_JSON: "json",
    ARTIFACT_SPECIALS_SUMMARY_CSV: "csv",
    ARTIFACT_SPECIALS_SUMMARY_JSON: "json",
    ARTIFACT_SPECIALS_SUMMARY_PDF: "pdf",
    ARTIFACT_PARALEGAL_CHRONOLOGY_MD: "md",
    ARTIFACT_EXTRACTION_NOTES_MD: "md",
    ARTIFACT_PATIENT_CHRONOLOGIES_JSON: "json",
}


VALID_DOWNLOAD_ARTIFACT_TYPES: tuple[str, ...] = tuple(ARTIFACT_EXTENSION_MAP.keys())


# Artifact types expected when a full pipeline run succeeds.
REQUIRED_PIPELINE_ARTIFACT_TYPES: tuple[str, ...] = (
    ARTIFACT_PDF,
    ARTIFACT_CSV,
    ARTIFACT_JSON,
    ARTIFACT_DOCX,
    ARTIFACT_PROVIDER_DIRECTORY_CSV,
    ARTIFACT_PROVIDER_DIRECTORY_JSON,
    ARTIFACT_MISSING_RECORDS_CSV,
    ARTIFACT_MISSING_RECORDS_JSON,
    ARTIFACT_MISSING_RECORD_REQUESTS_CSV,
    ARTIFACT_MISSING_RECORD_REQUESTS_JSON,
    ARTIFACT_MISSING_RECORD_REQUESTS_MD,
    ARTIFACT_BILLING_LINES_CSV,
    ARTIFACT_BILLING_LINES_JSON,
    ARTIFACT_SPECIALS_SUMMARY_CSV,
    ARTIFACT_SPECIALS_SUMMARY_JSON,
    ARTIFACT_SPECIALS_SUMMARY_PDF,
    ARTIFACT_PARALEGAL_CHRONOLOGY_MD,
    ARTIFACT_EXTRACTION_NOTES_MD,
)


def is_valid_artifact_type(artifact_type: str) -> bool:
    return artifact_type in ARTIFACT_EXTENSION_MAP


def artifact_extension(artifact_type: str) -> str:
    return ARTIFACT_EXTENSION_MAP.get(artifact_type, artifact_type)


def missing_required_types(artifact_types: Iterable[str]) -> list[str]:
    known = set(artifact_types)
    return [atype for atype in REQUIRED_PIPELINE_ARTIFACT_TYPES if atype not in known]
