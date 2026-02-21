"""
Step 2 — Text acquisition (embedded text first, OCR fallback).
If embedded text is non-trivial (>= 50 chars, not mostly whitespace), keep it.
Else run Tesseract OCR once on the page image.
"""
from __future__ import annotations

import logging
import re
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF

from packages.shared.models import Page, Warning

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 50
_TESSERACT_AVAILABLE: bool | None = None
_OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "30"))
_OCR_TOTAL_TIMEOUT_SECONDS = int(os.getenv("OCR_TOTAL_TIMEOUT_SECONDS", "600"))
_OCR_DPI = int(os.getenv("OCR_DPI", "200"))
_OCR_WORKERS = max(1, int(os.getenv("OCR_WORKERS", "2")))
_OCR_DISABLED = os.getenv("DISABLE_OCR", "").strip().lower() in {"1", "true", "yes", "on"}
_OCR_CONFIG = os.getenv("OCR_TESSERACT_CONFIG", "--oem 1 --psm 6").strip()


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


def _ocr_page(pdf_path: str, page_index: int, *, dpi: int, config: str, doc: fitz.Document | None = None) -> str:
    """Run Tesseract OCR on a single page rendered as an image."""
    try:
        import pytesseract
        from PIL import Image
        import io

        owned_doc = False
        if doc is None:
            doc = fitz.open(pdf_path)
            owned_doc = True
        try:
            page = doc[page_index]
            try:
                pix = page.get_pixmap(dpi=dpi)
            except Exception as exc:
                logger.error(f"Could not render page {page_index} for OCR: {exc}")
                return ""
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            text = pytesseract.image_to_string(img, lang="eng", config=config, timeout=_OCR_TIMEOUT_SECONDS)
            return text.strip()
        finally:
            try:
                if owned_doc:
                    doc.close()
            finally:
                try:
                    del img
                except Exception:
                    pass
                try:
                    del img_data
                except Exception:
                    pass
                try:
                    del pix
                except Exception:
                    pass
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

    if _OCR_DISABLED:
        for page in pages:
            if _is_meaningful(page.text):
                continue
            warnings.append(Warning(
                code="OCR_DISABLED",
                message=f"OCR disabled; page {page.page_number} has insufficient embedded text",
                page=page.page_number,
                document_id=page.source_document_id,
            ))
        return pages, ocr_count, warnings

    if not _check_tesseract():
        for page in pages:
            if _is_meaningful(page.text):
                continue
            warnings.append(Warning(
                code="OCR_UNAVAILABLE",
                message=f"Page {page.page_number} has insufficient embedded text and Tesseract is not available",
                page=page.page_number,
                document_id=page.source_document_id,
            ))
        return pages, ocr_count, warnings

    candidates: list[int] = []
    for i, page in enumerate(pages):
        if not _is_meaningful(page.text):
            candidates.append(i)

    if not candidates:
        return pages, ocr_count, warnings

    logger.info(f"OCR start: {len(candidates)} pages (dpi={_OCR_DPI}, workers={_OCR_WORKERS})")
    start_time = time.monotonic()
    deadline = start_time + _OCR_TOTAL_TIMEOUT_SECONDS

    def _mark_budget_exceeded(from_index: int) -> None:
        for idx in candidates[from_index:]:
            p = pages[idx]
            warnings.append(Warning(
                code="OCR_BUDGET_EXCEEDED",
                message=f"OCR budget exceeded; skipped page {p.page_number}",
                page=p.page_number,
                document_id=p.source_document_id,
            ))

    if _OCR_WORKERS <= 1:
        doc = fitz.open(pdf_path)
        try:
            for pos, i in enumerate(candidates):
                if time.monotonic() >= deadline:
                    _mark_budget_exceeded(pos)
                    break
                page = pages[i]
                t0 = time.monotonic()
                ocr_text = _ocr_page(pdf_path, i, dpi=_OCR_DPI, config=_OCR_CONFIG, doc=doc)
                elapsed = time.monotonic() - t0
                logger.info(f"OCR page {i+1}/{len(pages)} (source={page.source_document_id}) took {elapsed:.1f}s")
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
        finally:
            doc.close()
    else:
        submitted: list[int] = []
        with ThreadPoolExecutor(max_workers=_OCR_WORKERS) as executor:
            future_map = {}
            for pos, i in enumerate(candidates):
                if time.monotonic() >= deadline:
                    _mark_budget_exceeded(pos)
                    break
                def _task(idx: int) -> tuple[str, float]:
                    t0 = time.monotonic()
                    text = _ocr_page(pdf_path, idx, dpi=_OCR_DPI, config=_OCR_CONFIG, doc=None)
                    return text, time.monotonic() - t0
                future = executor.submit(_task, i)
                future_map[future] = i
                submitted.append(i)
            for future in as_completed(future_map):
                i = future_map[future]
                page = pages[i]
                try:
                    ocr_text, elapsed = future.result()
                except Exception as exc:
                    logger.error(f"OCR failed for page {i}: {exc}")
                    ocr_text = ""
                    elapsed = 0.0
                logger.info(f"OCR page {i+1}/{len(pages)} (source={page.source_document_id}) took {elapsed:.1f}s")
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
