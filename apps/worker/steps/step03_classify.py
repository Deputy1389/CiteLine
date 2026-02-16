"""
Step 3 — Page type classification (rule-based).
Assign page_type using priority-ordered keyword heuristics.
"""
from __future__ import annotations

import re

from packages.shared.models import Page, PageType, Warning

# Priority-ordered classification rules: (page_type, keywords_tuple)
_RULES: list[tuple[PageType, tuple[str, ...]]] = [
    (PageType.OPERATIVE_REPORT, (
        "operative report", "procedure", "anesthesia", "pre-op", "post-op",
        "surgical", "operation",
    )),
    (PageType.IMAGING_REPORT, (
        "impression", "findings", "technique", "radiology", "mri ", " ct ",
        "x-ray", "ultrasound", "imaging", "study date",
    )),
    (PageType.LAB_REPORT, (
        "lab results", "complete blood count", "cbc", "cmp", "bmp",
        "urinalysis", "hemoglobin", "hematocrit", "reference range",
        "specimen", "collected date", "resulted", "glucose",
        "platelet", "white blood cell", "wbc", "lipid panel",
    )),
    (PageType.DISCHARGE_SUMMARY, (
        "discharge summary", "hospital course", "discharge diagnosis",
        "discharge instructions", "final diagnosis", "condition on discharge",
        "discharge medications", "admission date", "discharge date",
    )),
    (PageType.BILLING, (
        "statement", "charges", "balance", "total due", "cpt", "hcfa",
        "ub-04", "invoice", "ledger", "amount due", "billing",
    )),
    (PageType.PT_NOTE, (
        "physical therapy", "pt daily note", "exercise", "plan of care",
        "visit #", "rehabilitation", "rom ", "therapeutic exercise",
    )),
    (PageType.ADMINISTRATIVE, (
        "fax cover", "authorization", "release of information", " roi ",
        "request for records", "records sent", "hipaa",
    )),
    (PageType.CLINICAL_NOTE, (
        "chief complaint", "history of present illness", "assessment",
        "plan:", "ros ", "review of systems", "physical exam",
        "vital signs", "medications", "allergies",
    )),
]


def classify_page(page: Page) -> tuple[PageType, int]:
    """
    Classify a single page. Returns (page_type, confidence).
    Confidence: 80+ for strong match, 50 for weak.
    """
    text_lower = page.text.lower()
    best_type = PageType.OTHER
    best_conf = 30

    for page_type, keywords in _RULES:
        matches = sum(1 for kw in keywords if kw in text_lower)
        conf = 0
        if matches >= 2:
            conf = min(90, 60 + matches * 10)
        elif matches == 1:
            conf = 50
        
        # specific logic: if we already have a strong match, only switch if this one is stronger
        if conf > best_conf:
            best_type = page_type
            best_conf = conf
    
    return best_type, best_conf


def classify_pages(pages: list[Page]) -> tuple[list[Page], list[Warning]]:
    """
    Classify all pages and assign page_type.
    Returns (updated_pages, warnings).
    """
    warnings: list[Warning] = []

    for page in pages:
        page_type, confidence = classify_page(page)
        page.page_type = page_type

        if confidence < 50:
            warnings.append(Warning(
                code="PAGE_TYPE_LOW_CONF",
                message=f"Page {page.page_number} classified as '{page_type.value}' with low confidence ({confidence})",
                page=page.page_number,
                document_id=page.source_document_id,
            ))

    return pages, warnings
