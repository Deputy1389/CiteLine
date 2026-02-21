"""
Post-process PDF to insert internal link annotations using render_manifest.json.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any

from pypdf import PdfReader, PdfWriter

from apps.worker.steps.export_render.render_manifest import parse_appendix_anchor, parse_chron_anchor


def _find_label_rect(page, label: str) -> tuple[float, float, float, float] | None:
    """
    Find the first rectangle for a text label on the page.
    Uses text extraction visitor for a best-effort bounding box.
    """
    label_norm = re.sub(r"\s+", " ", label.strip())
    found: tuple[float, float, float, float] | None = None

    def visitor_text(text, cm, tm, fontDict, fontSize):
        nonlocal found
        if found is not None:
            return
        if not text or not text.strip():
            return
        key = re.sub(r"\s+", " ", text.strip())
        if key != label_norm:
            return
        x, y = tm[4], tm[5]
        w = fontDict.get("Widths", [])[0] if fontDict else 40
        h = fontSize
        found = (x, y, x + w + 140, y + h + 8)

    page.extract_text(visitor_text=visitor_text)
    return found


def add_internal_links(pdf_bytes: bytes, manifest: dict[str, Any]) -> bytes:
    """
    Insert internal link annotations for citations using the manifest mapping.
    This is a best-effort pass; if a target cannot be located, the link is skipped.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    # Build anchor destinations based on simple text search.
    # We expect anchors in text like "Page 12" and a fixed structure.
    anchor_page_map: dict[str, int] = {}
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        for anchor in manifest.get("appendix_anchors", []):
            parsed = parse_appendix_anchor(anchor)
            if not parsed:
                continue
            _doc_id, page_no = parsed
            if f"Page {page_no}" in text:
                anchor_page_map[anchor] = i
        for anchor in manifest.get("chron_anchors", []):
            parsed = parse_chron_anchor(anchor)
            if not parsed:
                continue
            if parsed in text:
                anchor_page_map[anchor] = i

    # Add link annotations by scanning pages for citation labels.
    for i, page in enumerate(reader.pages):
        label_rect = _find_label_rect(page, "Citation(s):")
        if not label_rect:
            continue
        x0, y0, x1, y1 = label_rect
        for _from_anchor, to_anchors in (manifest.get("forward_links") or {}).items():
            if not to_anchors:
                continue
            target_page = anchor_page_map.get(to_anchors[0])
            if target_page is None:
                continue
            writer.add_link(
                pagenum=i,
                pagedest=target_page,
                rect=(x0, y0, x1, y1),
                border=[0, 0, 0],
            )

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
