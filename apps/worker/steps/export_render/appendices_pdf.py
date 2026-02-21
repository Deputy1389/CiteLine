"""
Appendix builders for PDF export.
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from apps.worker.steps.events.report_quality import sanitize_for_report
from apps.worker.steps.export_render.common import (
    _appendix_dx_line_ok,
    _appendix_dx_line_generic,
    _sanitize_render_sentence,
    _sanitize_citation_display,
)
from apps.worker.steps.export_render.render_manifest import appendix_anchor, parse_chron_anchor
from apps.worker.steps.export_render.medication_utils import (
    _extract_medication_changes,
    _extract_medication_change_rows,
)
from apps.worker.steps.export_render.extraction_utils import (
    _extract_diagnosis_items,
    _extract_pro_items,
    _extract_sdoh_items,
    _contradiction_flags,
)
from apps.worker.steps.export_render.gap_utils import _material_gap_rows

if TYPE_CHECKING:
    from packages.shared.models import Citation, Event, Gap, Provider
    from apps.worker.project.models import ChronologyProjectionEntry


def _public_base_url() -> str:
    raw = (os.getenv("CITELINE_PUBLIC_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "http://localhost:8000").strip()
    return raw.rstrip("/")


def _build_record_packet_rows(
    entries: list[ChronologyProjectionEntry],
    all_citations: list[Citation] | None,
    page_map: dict[int, tuple[str, int]] | None,
) -> list[dict[str, str]]:
    if not all_citations:
        return []
    cited_pages_by_file: dict[str, set[int]] = {}
    cite_pat = re.compile(r"([^,]+?)\s+p\.\s*(\d+)", re.IGNORECASE)
    for entry in entries:
        cite_text = str(getattr(entry, "citation_display", "") or "")
        for m in cite_pat.finditer(cite_text):
            fname = re.sub(r"\s+", " ", m.group(1).strip()).lower()
            page_no = int(m.group(2))
            if page_no <= 0:
                continue
            cited_pages_by_file.setdefault(fname, set()).add(page_no)

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, int, str]] = set()
    for cit in sorted(all_citations, key=lambda c: (str(c.source_document_id), int(c.page_number), str(c.citation_id))):
        filename = str(cit.source_document_id)
        local_page = int(cit.page_number)
        if page_map and cit.page_number in page_map:
            mapped_name, mapped_local = page_map[cit.page_number]
            filename = mapped_name or filename
            local_page = int(mapped_local)
        if cited_pages_by_file:
            fname_key = re.sub(r"\s+", " ", filename.strip()).lower()
            allowed_pages = cited_pages_by_file.get(fname_key, set())
            if local_page not in allowed_pages:
                continue
        snippet = _sanitize_render_sentence((cit.snippet or "").strip())
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if len(snippet) > 180:
            snippet = snippet[:177].rstrip() + "..."
        key = (str(cit.source_document_id), int(local_page), snippet.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "source_document_id": str(cit.source_document_id),
                "filename": filename,
                "local_page": str(local_page),
                "snippet": snippet or "(No snippet available)",
            }
        )
    return rows


def _render_record_packet_index(
    rows: list[dict[str, str]],
    styles: Any,
    h1_style: ParagraphStyle,
    normal_style: ParagraphStyle,
    italic_style: ParagraphStyle,
) -> list:
    flowables: list = []
    flowables.append(Paragraph("Appendix G: Record Packet Citation Index", h1_style))
    flowables.append(Paragraph("Click a citation link to open the original packet at the referenced page.", italic_style))
    flowables.append(Spacer(1, 0.05 * inch))
    if not rows:
        flowables.append(Paragraph("No citation anchors were available for source packet linking.", normal_style))
        flowables.append(Spacer(1, 0.1 * inch))
        return flowables

    base = _public_base_url()
    link_style = ParagraphStyle("CitationLink", parent=styles["Normal"], textColor=colors.HexColor("#1D4ED8"), underlineWidth=0.5)
    detail_style = ParagraphStyle("CitationDetail", parent=styles["Normal"], fontSize=9, leading=12)
    max_rows = 160
    for idx, row in enumerate(rows[:max_rows], start=1):
        doc_id = row["source_document_id"]
        local_page = row["local_page"]
        href = f"{base}/documents/{quote(doc_id, safe='')}/download#page={quote(local_page, safe='')}"
        label = f"[{idx}] {row['filename']} p. {local_page}"
        flowables.append(Paragraph(f'<link href="{escape(href)}">{escape(label)}</link>', link_style))
        flowables.append(Paragraph(f"Snippet: {escape(row['snippet'])}", detail_style))
        flowables.append(Spacer(1, 0.04 * inch))
    if len(rows) > max_rows:
        flowables.append(
            Paragraph(
                f"Showing first {max_rows} citation anchors out of {len(rows)} total.",
                detail_style,
            )
        )
        flowables.append(Spacer(1, 0.05 * inch))
    flowables.append(Spacer(1, 0.1 * inch))
    return flowables


def build_appendix_sections(events: list[Event], gaps: list[Gap], providers: list[Provider], page_map: dict[int, tuple[str, int]] | None, styles: Any) -> list:
    flowables = []
    h2 = styles["Heading2"]
    flowables.append(Paragraph("Appendix: Critical Data", h2))
    flowables.append(Spacer(1, 0.2 * inch))
    return flowables


def build_projection_appendix_sections(
    entries: list[ChronologyProjectionEntry],
    gaps: list[Gap],
    page_map: dict[int, tuple[str, int]] | None,
    styles: Any,
    raw_events: list[Event] | None = None,
    all_citations: list[Citation] | None = None,
    missing_records_payload: dict | None = None,
    manifest=None,
) -> list:
    flowables: list = []
    h1_style = ParagraphStyle("H1Style", parent=styles["Heading1"], fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#2E548A"))
    normal_style = styles["Normal"]
    link_style = ParagraphStyle("AppendixLink", parent=styles["Normal"], textColor=colors.HexColor("#1D4ED8"), underlineWidth=0.5)

    if not all_citations:
        flowables.append(Paragraph("No citation anchors were available for source packet linking.", normal_style))
        return flowables

    event_label_map: dict[str, str] = {}
    for entry in entries:
        label = f"{entry.date_display or 'Undated'} | {entry.event_type_display or 'Event'}"
        event_label_map[str(entry.event_id)] = label

    allowed_anchors: set[str] | None = None
    if manifest:
        if manifest.back_links:
            allowed_anchors = set(manifest.back_links.keys())
        elif manifest.appendix_anchors:
            allowed_anchors = set(manifest.appendix_anchors)

    # Group citations by source document + local page.
    grouped: dict[tuple[str, int, str], list[str]] = {}
    for cit in sorted(all_citations, key=lambda c: (str(c.source_document_id), int(c.page_number), str(c.citation_id))):
        filename = str(cit.source_document_id)
        local_page = int(cit.page_number)
        if page_map and cit.page_number in page_map:
            mapped_name, mapped_local = page_map[cit.page_number]
            filename = mapped_name or filename
            local_page = int(mapped_local)
        anchor = appendix_anchor(str(cit.source_document_id), local_page)
        if allowed_anchors is not None and anchor not in allowed_anchors:
            continue
        key = (str(cit.source_document_id), local_page, filename)
        grouped.setdefault(key, [])
        snippet = _sanitize_render_sentence((cit.snippet or "").strip())
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if snippet:
            grouped[key].append(snippet)

    # Render appendix by document.
    doc_groups: dict[str, list[tuple[int, str, list[str]]]] = {}
    for (doc_id, page_no, filename), snippets in grouped.items():
        doc_groups.setdefault(doc_id, []).append((page_no, filename, snippets))

    for doc_id, pages in doc_groups.items():
        pages_sorted = sorted(pages, key=lambda x: x[0])
        doc_label = pages_sorted[0][1] if pages_sorted else doc_id
        flowables.append(Paragraph(f"Source Document: {doc_label}", h1_style))
        flowables.append(Paragraph('<a name="medical_record_appendix"/>', normal_style))
        flowables.append(Paragraph('<link href="#chronology_section_header">Back to Chronology</link>', link_style))
        flowables.append(Spacer(1, 0.06 * inch))

        for page_no, _, snippets in pages_sorted:
            anchor = appendix_anchor(doc_id, page_no)
            if manifest:
                manifest.add_appendix_anchor(anchor)
            flowables.append(Paragraph(f'<a name="{anchor}"/>Page {page_no}', normal_style))
            for snip in snippets[:4]:
                flowables.append(Paragraph(f"- {snip}", normal_style))

            if manifest and anchor in manifest.back_links:
                back_links = manifest.back_links.get(anchor, [])
                if back_links:
                    link_bits = []
                    for bid in back_links[:6]:
                        event_id = parse_chron_anchor(bid) or bid
                        label = event_label_map.get(event_id, bid)
                        link_bits.append(f'<link href="#{bid}">[{escape(label)}]</link>')
                    links = " ".join(link_bits)
                    flowables.append(Paragraph(f"Referenced by: {links}", link_style))

            flowables.append(Spacer(1, 0.08 * inch))

    return flowables



