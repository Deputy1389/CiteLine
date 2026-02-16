"""
Step 1 — PDF page split + numbering.
Uses PyMuPDF (fitz) to split each PDF into pages, extract embedded text,
and record Page objects with layout dimensions.
"""
from __future__ import annotations

import uuid

import fitz  # PyMuPDF

from packages.shared.models import Page, PageLayout, Warning


def split_pages(
    pdf_path: str,
    source_document_id: str,
    page_offset: int = 0,
    max_pages: int | None = None,
) -> tuple[list[Page], list[Warning]]:
    """
    Split a PDF into Page objects with embedded text if available.

    Args:
        pdf_path: Path to the PDF file on disk.
        source_document_id: ID of the source document.
        page_offset: Global page numbering offset (for multi-doc runs).
        max_pages: Maximum pages to process; None = no limit.

    Returns:
        (pages, warnings)
    """
    warnings: list[Warning] = []
    pages: list[Page] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        warnings.append(Warning(
            code="PDF_OPEN_ERROR",
            message=f"Cannot open PDF: {exc}",
            document_id=source_document_id,
        ))
        return pages, warnings

    total = doc.page_count
    limit = total
    if max_pages is not None and total > max_pages:
        limit = max_pages
        warnings.append(Warning(
            code="MAX_PAGES_EXCEEDED",
            message=f"PDF has {total} pages but max_pages={max_pages}; processing first {max_pages}",
            document_id=source_document_id,
        ))

    for i in range(limit):
        fitz_page = doc[i]
        page_number = page_offset + i + 1
        try:
            text = fitz_page.get_text("text") or ""
        except Exception as exc:
            # Some PDFs have font metadata PyMuPDF can't parse
            # (e.g. textfont.LAID). Fall back to empty text → OCR in step02.
            text = ""
            warnings.append(Warning(
                code="TEXT_EXTRACT_ERROR",
                message=f"Page {page_number}: embedded text extraction failed ({exc})",
                page=page_number,
                document_id=source_document_id,
            ))
        rect = fitz_page.rect

        layout = PageLayout(
            width=round(rect.width, 2),
            height=round(rect.height, 2),
            units="pt",
        )

        pages.append(Page(
            page_id=uuid.uuid4().hex[:16],
            source_document_id=source_document_id,
            page_number=page_number,
            text=text,
            text_source="embedded_pdf_text",
            layout=layout,
        ))

    doc.close()
    return pages, warnings
