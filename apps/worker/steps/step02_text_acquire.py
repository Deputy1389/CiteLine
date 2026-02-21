"""
Step 2 — Text acquisition (embedded text first, OCR fallback).
If embedded text is non-trivial (>= 50 chars, not mostly whitespace), keep it.
Else run Tesseract OCR once on the page image.
"""
from __future__ import annotations

import logging
import re
import os

import fitz  # PyMuPDF

from packages.shared.models import Page, Warning

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 50
_TESSERACT_AVAILABLE: bool | None = None
_OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "30"))


def _check_tesseract() -> bool:
    """Check if Tesseract is available (cached)."""
    global _TESSERACT_AVAILABLE
    if _TESSERACT_AVAILABLE is not None:
        return _TESSERACT_AVAILABLE
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        _TESSERACT_AVAILABLE = True
    except Exception:
        _TESSERACT_AVAILABLE = False
        logger.warning("Tesseract not available — OCR fallback will be skipped")
    return _TESSERACT_AVAILABLE


def _is_meaningful(text: str) -> bool:
    """Check if text is meaningful (non-trivial content)."""
    stripped = text.strip()
    if len(stripped) < _MIN_TEXT_LENGTH:
        return False
    # Check if mostly whitespace
    non_ws = re.sub(r"\s+", "", stripped)
    if len(non_ws) < _MIN_TEXT_LENGTH // 2:
        return False
    return True


def _ocr_page(pdf_path: str, page_index: int) -> str:
    """Run Tesseract OCR on a single page rendered as an image."""
    try:
        import pytesseract
        from PIL import Image
        import io

        doc = fitz.open(pdf_path)
        try:
            page = doc[page_index]
            # Render at 300 DPI for good OCR quality
            try:
                pix = page.get_pixmap(dpi=300)
            except Exception as exc:
                logger.error(f"Could not render page {page_index} for OCR: {exc}")
                return ""
            img_data = pix.tobytes("png")
        finally:
            doc.close()

        img = Image.open(io.BytesIO(img_data))
        text = pytesseract.image_to_string(img, lang="eng", timeout=_OCR_TIMEOUT_SECONDS)
        return text.strip()
    except RuntimeError as exc:
        # pytesseract raises RuntimeError on timeout
        logger.error(f"OCR timeout for page {page_index}: {exc}")
        return ""
    except Exception as exc:
        logger.error(f"OCR failed for page {page_index}: {exc}")
        return ""


def acquire_text(
    pages: list[Page],
    pdf_path: str,
) -> tuple[list[Page], int, list[Warning]]:
    """
    Ensure every page has meaningful text.
    Returns (updated_pages, ocr_count, warnings).
    """
    warnings: list[Warning] = []
    ocr_count = 0

    for i, page in enumerate(pages):
        if i % 25 == 0:
            logger.info(f"OCR progress: page {i+1}/{len(pages)} (source={page.source_document_id})")
        if _is_meaningful(page.text):
            continue  # embedded text is fine

        # Need OCR fallback
        if not _check_tesseract():
            warnings.append(Warning(
                code="OCR_UNAVAILABLE",
                message=f"Page {page.page_number} has insufficient embedded text and Tesseract is not available",
                page=page.page_number,
                document_id=page.source_document_id,
            ))
            continue

        ocr_text = _ocr_page(pdf_path, i)
        if ocr_text:
            page.text = ocr_text
            page.text_source = "ocr"
            ocr_count += 1
        else:
            warnings.append(Warning(
                code="OCR_NO_TEXT",
                message=f"OCR returned no text for page {page.page_number}",
                page=page.page_number,
                document_id=page.source_document_id,
            ))

    return pages, ocr_count, warnings
