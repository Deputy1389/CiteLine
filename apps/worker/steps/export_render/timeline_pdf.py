"""
Timeline rendering logic for PDF export.
"""
from __future__ import annotations

import re
import logging
from datetime import date
from io import BytesIO
from typing import TYPE_CHECKING, Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    PageBreak,
    Spacer,
)
logger = logging.getLogger(__name__)

from apps.worker.steps.export_render.common import (
    _date_str,
    _provider_name,
    _facts_text,
    _normalized_encounter_label,
    _clean_narrative_text,
    _clean_direct_snippet,
    _is_meta_language,
    parse_date_string,
)
from apps.worker.steps.export_render.timeline_render_utils import _render_entry
from apps.worker.steps.export_render.appendices_pdf import (
    build_appendix_sections,
    build_projection_appendix_sections,
)
from apps.worker.steps.export_render.render_manifest import (
    RenderManifest,
    chron_anchor,
    appendix_anchor,
)
from apps.worker.steps.export_render.moat_section import build_moat_section_flowables

if TYPE_CHECKING:
    from packages.shared.models import Event, Gap, Provider, CaseInfo, Citation
    from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry


def generate_executive_summary(events: list[Event], matter_title: str, case_info: CaseInfo | None = None) -> str:
    from apps.worker.steps.export_render.extraction_utils import _scan_incident_signal
    page_text: dict[int, str] = {}
    for e in events:
        for p in (e.source_page_numbers or []):
            if p not in page_text:
                page_text[p] = " ".join(f.text or "" for f in e.facts)
    incident = _scan_incident_signal(page_text, None)
    summary = f"Executive Summary for {matter_title}\n\n"
    if incident.get("found"):
        summary += f"Date of Injury: {incident['doi'] or 'Not established'}\n"
        summary += f"Mechanism: {incident['mechanism'] or 'Not established'}\n\n"
    else:
        summary += "Incident details not established from available records.\n\n"
    summary += f"Total encounters analyzed: {len(events)}\n"
    return summary


def _build_events_flowables(events: list[Event], providers: list[Provider], page_map: dict[int, tuple[str, int]] | None, styles: Any) -> list:
    flowables = []
    h2 = styles["Heading2"]
    normal = styles["Normal"]
    for event in events:
        dstr = _date_str(event)
        pname = _provider_name(event, providers)
        etype = (event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)).replace("_", " ").title()
        flowables.append(Paragraph(f"{dstr} | {pname} | {etype}", h2))
        flowables.append(Paragraph(_facts_text(event), normal))
        flowables.append(Spacer(1, 0.1 * inch))
    return flowables


def _build_projection_flowables(
    projection: ChronologyProjection,
    raw_events: list[Event] | None,
    page_map: dict[int, tuple[str, int]] | None,
    styles: Any,
    manifest: RenderManifest | None = None,
    all_citations: list[Citation] | None = None,
) -> list:
    flowables = []
    h2 = styles["Heading2"]
    normal = styles["Normal"]
    meta_style = ParagraphStyle("MetaStyle", parent=normal, fontSize=8, textColor=colors.grey)
    fact_style = ParagraphStyle("FactStyle", parent=normal, bulletIndent=12, leftIndent=24)
    date_style = ParagraphStyle("DateStyle", parent=h2, fontSize=11, spaceBefore=6, spaceAfter=2)

    from apps.worker.lib.claim_ledger_lite import build_claim_ledger_lite
    claims_list = build_claim_ledger_lite(projection.entries, raw_events=raw_events)
    from collections import defaultdict
    claims_by_event = defaultdict(list)
    for c in claims_list:
        eid = c.get("event_id")
        if eid:
            claims_by_event[eid].append(c)

    filename_doc_map = _build_filename_doc_map(all_citations, page_map)

    timeline_row_keys: set[str] = set()
    therapy_recent_signatures: dict[tuple[str, str], tuple[str, date]] = {}

    for entry in projection.entries:
        citation_links = _build_citation_links(entry, filename_doc_map)
        entry_flowables = _render_entry(
            entry=entry,
            date_style=date_style,
            fact_style=fact_style,
            meta_style=meta_style,
            timeline_row_keys=timeline_row_keys,
            therapy_recent_signatures=therapy_recent_signatures,
            claims_by_event=claims_by_event,
            extract_date_func=parse_date_string,
            chron_anchor=chron_anchor(entry.event_id),
            citation_links=citation_links,
            manifest=manifest,
        )
        if entry_flowables:
            flowables.extend(entry_flowables)
    return flowables


def generate_pdf(run_id: str, matter_title: str, events: list[Event], gaps: list[Gap], providers: list[Provider], page_map: dict[int, tuple[str, int]] | None = None) -> bytes:
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=letter)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    template = PageTemplate(id="test", frames=[frame])
    doc.addPageTemplates([template])
    styles = getSampleStyleSheet()
    flowables = [Paragraph(f"Medical Chronology: {matter_title}", styles["Title"]), Spacer(1, 0.2 * inch)]
    flowables.extend(_build_events_flowables(events, providers, page_map, styles))
    flowables.extend(build_appendix_sections(events, gaps, providers, page_map, styles))
    doc.build(flowables)
    return buffer.getvalue()


def generate_pdf_from_projection(
    matter_title: str,
    projection: ChronologyProjection,
    gaps: list[Gap],
    narrative_synthesis: str | None = None,
    appendix_entries: list[ChronologyProjectionEntry] | None = None,
    raw_events: list[Event] | None = None,
    all_citations: list[Citation] | None = None,
    page_map: dict[int, tuple[str, int]] | None = None,
    care_window: tuple[date, date] | None = None,
    missing_records_payload: dict | None = None,
    evidence_graph_payload: dict | None = None,
    run_id: str | None = None,
) -> bytes:
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=18, spaceAfter=12)
    h1_style = ParagraphStyle("H1Style", parent=styles["Heading1"], fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#2E548A"))
    normal_style = styles["Normal"]

    manifest = RenderManifest()

    flowables = [Paragraph(f"Medical Chronology: {matter_title}", title_style)]

    # Moat section (top of document)
    flowables.append(Paragraph("Moat Analysis", h1_style))
    moat_flowables, moat_stats = build_moat_section_flowables(
        projection_entries=projection.entries,
        evidence_graph_payload=evidence_graph_payload,
        missing_records_payload=missing_records_payload,
        styles=styles,
    )
    flowables.extend(moat_flowables)

    # Executive Summary (after moat)
    flowables.append(PageBreak())
    flowables.append(Paragraph("Executive Summary", h1_style))
    if narrative_synthesis:
        from apps.worker.quality.text_quality import clean_text, is_garbage
        clean_narrative = _clean_narrative_text(clean_text(narrative_synthesis))
        for p_text in clean_narrative.split("\n\n"):
            if p_text.strip():
                if is_garbage(p_text):
                    flowables.append(Paragraph("Content present but low-quality/duplicative; see cited source.", normal_style))
                else:
                    flowables.append(Paragraph(p_text.strip().replace("\n", "<br/>"), normal_style))
                flowables.append(Spacer(1, 0.1 * inch))
    else:
        flowables.append(Paragraph("No executive summary available.", normal_style))
        flowables.append(Spacer(1, 0.1 * inch))

    # Timeline
    flowables.append(PageBreak())
    flowables.append(Paragraph('<a name="chronology_section_header"/>Chronological Medical Timeline', h1_style))
    timeline_flowables = _build_projection_flowables(
        projection,
        raw_events,
        page_map,
        styles,
        manifest=manifest,
        all_citations=all_citations,
    )
    if not timeline_flowables:
        flowables.append(Paragraph("No timeline events met the criteria for inclusion in this view.", normal_style))
    else:
        flowables.extend(timeline_flowables)

    # Appendix
    flowables.append(PageBreak())
    flowables.append(Paragraph("Medical Record Appendix", h1_style))
    flowables.extend(build_projection_appendix_sections(
        appendix_entries or projection.entries,
        gaps,
        page_map,
        styles,
        raw_events=raw_events,
        all_citations=all_citations,
        missing_records_payload=missing_records_payload,
        manifest=manifest,
    ))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.drawString(inch, 0.75 * inch, f"Medical Chronology: {matter_title}")
        canvas.drawRightString(letter[0] - inch, 0.75 * inch, f"Page {doc.page}")
        canvas.restoreState()

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    template = PageTemplate(id="test", frames=[frame], onPage=footer)
    doc.addPageTemplates([template])
    doc.build(flowables)
    if run_id:
        from dataclasses import asdict
        from packages.shared.storage import save_artifact
        import json
        manifest_payload = asdict(manifest)
        if evidence_graph_payload and isinstance(evidence_graph_payload, dict):
            ext = evidence_graph_payload.get("extensions", {}) or {}
            if "quality_gate" in ext:
                manifest_payload["quality_gate"] = ext.get("quality_gate")
        if moat_stats:
            manifest_payload["moat_quality_stats"] = moat_stats
        manifest_bytes = json.dumps(manifest_payload, indent=2).encode("utf-8")
        save_artifact(run_id, "render_manifest.json", manifest_bytes)
    pdf_bytes = buffer.getvalue()
    try:
        from apps.worker.steps.export_render.pdf_linker import add_internal_links
        if manifest.forward_links:
            pdf_bytes = add_internal_links(pdf_bytes, json.loads(manifest_bytes.decode("utf-8")))
    except Exception as exc:
        logger.warning(f"PDF link post-process failed: {exc}")
    return pdf_bytes


def _normalize_filename(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def _build_filename_doc_map(
    all_citations: list[Citation] | None,
    page_map: dict[int, tuple[str, int]] | None,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not all_citations:
        return mapping
    for cit in all_citations:
        filename = str(cit.source_document_id)
        if page_map and cit.page_number in page_map:
            mapped_name, _mapped_page = page_map[cit.page_number]
            if mapped_name:
                filename = mapped_name
        key = _normalize_filename(filename)
        if key and key not in mapping:
            mapping[key] = str(cit.source_document_id)
    return mapping


def _parse_citation_display(citation_display: str) -> list[tuple[str, int]]:
    if not citation_display:
        return []
    cite_pat = re.compile(r"([^,|;]+?)\s+p\.\s*(\d+)", re.IGNORECASE)
    refs: list[tuple[str, int]] = []
    for m in cite_pat.finditer(citation_display):
        fname = re.sub(r"\s+", " ", m.group(1).strip())
        try:
            page = int(m.group(2))
        except ValueError:
            continue
        if page <= 0:
            continue
        refs.append((fname, page))
    return refs


def _build_citation_links(
    entry: ChronologyProjectionEntry,
    filename_doc_map: dict[str, str],
) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for fname, page in _parse_citation_display(entry.citation_display or ""):
        doc_id = filename_doc_map.get(_normalize_filename(fname))
        if not doc_id:
            continue
        anchor = appendix_anchor(doc_id, page)
        links.append({"label": f"{fname} p. {page}", "anchor": anchor})
    return links
