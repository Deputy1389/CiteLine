"""
Step 4 — Document segmentation.
Group pages into Document objects representing contiguous runs of similar content.
"""
from __future__ import annotations

import uuid

from packages.shared.models import (
    Document,
    DocumentType,
    Page,
    PageType,
    PageTypeSpan,
    Warning,
)

_TYPE_TO_DOC_TYPE: dict[PageType, DocumentType] = {
    PageType.BILLING: DocumentType.MEDICAL_BILL,
    PageType.CLINICAL_NOTE: DocumentType.MEDICAL_RECORD,
    PageType.IMAGING_REPORT: DocumentType.MEDICAL_RECORD,
    PageType.OPERATIVE_REPORT: DocumentType.MEDICAL_RECORD,
    PageType.PT_NOTE: DocumentType.MEDICAL_RECORD,
    PageType.LAB_REPORT: DocumentType.MEDICAL_RECORD,
    PageType.ADMINISTRATIVE: DocumentType.UNKNOWN,
    PageType.OTHER: DocumentType.UNKNOWN,
}


def _dominant_type(pages: list[Page]) -> PageType:
    """Find the most common page type in a list of pages."""
    counts: dict[PageType, int] = {}
    for p in pages:
        pt = p.page_type or PageType.OTHER
        counts[pt] = counts.get(pt, 0) + 1
    return max(counts, key=lambda k: counts[k])


def _build_spans(pages: list[Page]) -> list[PageTypeSpan]:
    """Build page type spans from a contiguous run of pages."""
    if not pages:
        return []

    spans: list[PageTypeSpan] = []
    current_type = pages[0].page_type or PageType.OTHER
    start_page = pages[0].page_number

    for i in range(1, len(pages)):
        pt = pages[i].page_type or PageType.OTHER
        if pt != current_type:
            spans.append(PageTypeSpan(
                page_start=start_page,
                page_end=pages[i - 1].page_number,
                page_type=current_type,
            ))
            current_type = pt
            start_page = pages[i].page_number

    spans.append(PageTypeSpan(
        page_start=start_page,
        page_end=pages[-1].page_number,
        page_type=current_type,
    ))
    return spans


def segment_documents(
    pages: list[Page],
    source_document_id: str,
) -> tuple[list[Document], list[Warning]]:
    """
    Segment pages into Document objects by detecting type changes.
    Returns (documents, warnings).
    """
    warnings: list[Warning] = []
    if not pages:
        return [], warnings

    documents: list[Document] = []
    current_group: list[Page] = [pages[0]]

    for i in range(1, len(pages)):
        prev_type = pages[i - 1].page_type or PageType.OTHER
        curr_type = pages[i].page_type or PageType.OTHER

        # Break on major type changes (e.g., clinical → billing)
        if _TYPE_TO_DOC_TYPE.get(curr_type) != _TYPE_TO_DOC_TYPE.get(prev_type):
            documents.append(_make_document(current_group, source_document_id))
            current_group = [pages[i]]
        else:
            current_group.append(pages[i])

    # Final group
    if current_group:
        documents.append(_make_document(current_group, source_document_id))

    return documents, warnings


def _make_document(pages: list[Page], source_document_id: str) -> Document:
    dominant = _dominant_type(pages)
    return Document(
        document_id=uuid.uuid4().hex[:16],
        source_document_id=source_document_id,
        page_start=pages[0].page_number,
        page_end=pages[-1].page_number,
        page_types=_build_spans(pages),
        declared_document_type=_TYPE_TO_DOC_TYPE.get(dominant, DocumentType.UNKNOWN),
        confidence=70,
    )
