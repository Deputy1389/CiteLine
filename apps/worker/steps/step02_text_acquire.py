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
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF

from packages.shared.models import Page, Warning
from packages.db.database import get_session
from packages.db.models import SourceDocument, Run, OCRCache

logger = logging.getLogger(__name__)

_MIN_TEXT_LENGTH = 50
_TESSERACT_AVAILABLE: bool | None = None
_OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "30"))
_OCR_TOTAL_TIMEOUT_SECONDS = int(os.getenv("OCR_TOTAL_TIMEOUT_SECONDS", "600"))
_OCR_DPI = int(os.getenv("OCR_DPI", "200"))
_OCR_WORKERS = max(1, int(os.getenv("OCR_WORKERS", "2")))
_OCR_DISABLED = os.getenv("DISABLE_OCR", "").strip().lower() in {"1", "true", "yes", "on"}
_OCR_CONFIG = os.getenv("OCR_TESSERACT_CONFIG", "--oem 1 --psm 6").strip()
_OCR_MODE = os.getenv("OCR_MODE", "full").strip().lower()
_OCR_FAST_LIMIT = int(os.getenv("OCR_FAST_LIMIT", "50"))
_OCR_SAMPLE_EVERY = int(os.getenv("OCR_SAMPLE_EVERY", "5"))


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


def _page_needs_ocr(page_text: str, fitz_page: fitz.Page) -> bool:
    stripped = (page_text or "").strip()
    if _is_meaningful(stripped):
        return False
    # Blank or separator page: no text + no images
    try:
        images = fitz_page.get_images()
        if len(stripped) < 5 and not images:
            return False
    except Exception:
        pass
    # Detect pages with no fonts (likely scanned)
    try:
        blocks = fitz_page.get_text("dict").get("blocks", [])
        font_spans = 0
        for b in blocks:
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("font"):
                        font_spans += 1
        if font_spans == 0:
            return True
    except Exception:
        pass
    # Low density text layer: likely headers/watermarks only
    non_ws = re.sub(r"\s+", "", stripped)
    if 0 < len(non_ws) < 200:
        return True
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


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _quality_warning(text: str) -> bool:
    if not text:
        return True
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) < 40:
        return True
    non_ascii = sum(1 for ch in clean if ord(ch) > 127)
    if non_ascii / max(1, len(clean)) > 0.2:
        return True
    alpha_num = re.sub(r"[^A-Za-z0-9]", "", clean)
    if len(alpha_num) / max(1, len(clean)) < 0.3:
        return True
    return False


def _update_ocr_metrics(run_id: str | None, payload: dict) -> None:
    if not run_id:
        return
    try:
        with get_session() as session:
            run = session.query(Run).filter(Run.id == run_id).one_or_none()
            if not run:
                return
            metrics = run.metrics_json or {}
            metrics["ocr"] = payload
            run.metrics_json = metrics
    except Exception as exc:
        logger.warning(f"Failed to update OCR metrics for run {run_id}: {exc}")


def acquire_text(
    pages: list[Page],
    pdf_path: str,
    run_id: str | None = None,
) -> tuple[list[Page], int, list[Warning]]:
    """
    Ensure every page has meaningful text.
    Returns (updated_pages, ocr_count, warnings).
    """
    warnings: list[Warning] = []
    ocr_count = 0

    if _OCR_DISABLED or _OCR_MODE == "off":
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
    page_doc_map: dict[str, SourceDocument] = {}
    try:
        with get_session() as session:
            ids = sorted({p.source_document_id for p in pages if p.source_document_id})
            if ids:
                for doc in session.query(SourceDocument).filter(SourceDocument.id.in_(ids)).all():
                    page_doc_map[str(doc.id)] = doc
    except Exception as exc:
        logger.warning(f"Failed to load source document metadata for OCR cache: {exc}")

    doc = fitz.open(pdf_path)
    try:
        for i, page in enumerate(pages):
            if _page_needs_ocr(page.text, doc[i]):
                candidates.append(i)
    finally:
        doc.close()

    if _OCR_MODE == "fast":
        candidates = candidates[:_OCR_FAST_LIMIT]
    elif _OCR_MODE == "sample":
        if _OCR_SAMPLE_EVERY > 1:
            candidates = [idx for pos, idx in enumerate(candidates) if (pos % _OCR_SAMPLE_EVERY) == 0]

    if not candidates:
        return pages, ocr_count, warnings

    logger.info(f"OCR start: {len(candidates)} pages (dpi={_OCR_DPI}, workers={_OCR_WORKERS})")
    start_time = time.monotonic()
    deadline = start_time + _OCR_TOTAL_TIMEOUT_SECONDS
    cached_hits = 0
    processed = 0
    _update_ocr_metrics(run_id, {
        "pages_done": 0,
        "pages_total": len(candidates),
        "elapsed_seconds": 0,
        "cached_hits": 0,
        "mode": _OCR_MODE,
        "dpi": _OCR_DPI,
        "workers": _OCR_WORKERS,
    })

def _mark_budget_exceeded(from_index: int) -> None:
    for idx in candidates[from_index:]:
        p = pages[idx]
        warnings.append(Warning(
            code="OCR_BUDGET_EXCEEDED",
            message=f"OCR budget exceeded; skipped page {p.page_number}",
            page=p.page_number,
            document_id=p.source_document_id,
        ))
    _update_ocr_metrics(run_id, {
        "pages_done": processed,
        "pages_total": len(candidates),
        "elapsed_seconds": int(time.monotonic() - start_time),
        "cached_hits": cached_hits,
        "budget_exceeded": True,
    })

    def _lookup_cache(idx: int) -> str | None:
        page = pages[idx]
        doc_meta = page_doc_map.get(str(page.source_document_id))
        if not doc_meta:
            return None
        try:
            with get_session() as session:
                row = (
                    session.query(OCRCache)
                    .filter(OCRCache.source_document_id == str(page.source_document_id))
                    .filter(OCRCache.page_number == int(page.page_number))
                    .one_or_none()
                )
                if row and row.document_sha256 == doc_meta.sha256 and row.dpi == _OCR_DPI:
                    return str(row.text or "")
        except Exception as exc:
            logger.warning(f"OCR cache lookup failed for page {page.page_number}: {exc}")
        return None

    def _store_cache(idx: int, text: str) -> None:
        page = pages[idx]
        doc_meta = page_doc_map.get(str(page.source_document_id))
        if not doc_meta or not text:
            return
        try:
            with get_session() as session:
                row = OCRCache(
                    source_document_id=str(page.source_document_id),
                    document_sha256=doc_meta.sha256,
                    page_number=int(page.page_number),
                    text=text,
                    text_hash=_text_hash(text),
                    ocr_engine="tesseract",
                    dpi=_OCR_DPI,
                )
                session.add(row)
        except Exception as exc:
            logger.warning(f"OCR cache write failed for page {page.page_number}: {exc}")

    if _OCR_WORKERS <= 1:
        doc = fitz.open(pdf_path)
        try:
            for pos, i in enumerate(candidates):
                if time.monotonic() >= deadline:
                    _mark_budget_exceeded(pos)
                    break
                page = pages[i]
                cached = _lookup_cache(i)
                if cached:
                    page.text = cached
                    page.text_source = "ocr_cache"
                    cached_hits += 1
                    processed += 1
                    _update_ocr_metrics(run_id, {
                        "pages_done": processed,
                        "pages_total": len(candidates),
                        "elapsed_seconds": int(time.monotonic() - start_time),
                        "cached_hits": cached_hits,
                    })
                    continue
                t0 = time.monotonic()
                ocr_text = _ocr_page(pdf_path, i, dpi=_OCR_DPI, config=_OCR_CONFIG, doc=doc)
                elapsed = time.monotonic() - t0
                logger.info(f"OCR page {i+1}/{len(pages)} (source={page.source_document_id}) took {elapsed:.1f}s")
                if ocr_text:
                    page.text = ocr_text
                    page.text_source = "ocr"
                    ocr_count += 1
                    _store_cache(i, ocr_text)
                    if _quality_warning(ocr_text):
                        warnings.append(Warning(
                            code="OCR_QUALITY_LOW",
                            message=f"OCR text quality appears low for page {page.page_number}",
                            page=page.page_number,
                            document_id=page.source_document_id,
                        ))
                else:
                    warnings.append(Warning(
                        code="OCR_NO_TEXT",
                        message=f"OCR returned no text for page {page.page_number}",
                        page=page.page_number,
                        document_id=page.source_document_id,
                    ))
                processed += 1
                _update_ocr_metrics(run_id, {
                    "pages_done": processed,
                    "pages_total": len(candidates),
                    "elapsed_seconds": int(time.monotonic() - start_time),
                    "cached_hits": cached_hits,
                })
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
                cached = _lookup_cache(i)
                if cached:
                    page = pages[i]
                    page.text = cached
                    page.text_source = "ocr_cache"
                    cached_hits += 1
                    processed += 1
                    _update_ocr_metrics(run_id, {
                        "pages_done": processed,
                        "pages_total": len(candidates),
                        "elapsed_seconds": int(time.monotonic() - start_time),
                        "cached_hits": cached_hits,
                    })
                    continue
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
                    _store_cache(i, ocr_text)
                    if _quality_warning(ocr_text):
                        warnings.append(Warning(
                            code="OCR_QUALITY_LOW",
                            message=f"OCR text quality appears low for page {page.page_number}",
                            page=page.page_number,
                            document_id=page.source_document_id,
                        ))
                else:
                    warnings.append(Warning(
                        code="OCR_NO_TEXT",
                        message=f"OCR returned no text for page {page.page_number}",
                        page=page.page_number,
                        document_id=page.source_document_id,
                    ))
                processed += 1
                _update_ocr_metrics(run_id, {
                    "pages_done": processed,
                    "pages_total": len(candidates),
                    "elapsed_seconds": int(time.monotonic() - start_time),
                    "cached_hits": cached_hits,
                })

    return pages, ocr_count, warnings
