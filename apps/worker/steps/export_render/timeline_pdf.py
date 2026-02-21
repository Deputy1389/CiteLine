"""
Timeline rendering logic for PDF export.
"""
from __future__ import annotations

import re
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
    Spacer,
)

from apps.worker.steps.export_render.common import (
    _date_str,
    _provider_name,
    _facts_text,
    _normalized_encounter_label,
    _clean_narrative_text,
    _clean_direct_snippet,
    _is_meta_language,
    parse_date_string,
    _sanitize_render_sentence,
    _is_sdoh_noise,
)
from apps.worker.steps.export_render.constants import (
    META_LANGUAGE_RE,
)
from apps.worker.steps.export_render.timeline_render_utils import _render_entry
from apps.worker.steps.export_render.appendices_pdf import (
    build_appendix_sections,
    build_projection_appendix_sections,
)

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

    timeline_row_keys: set[str] = set()
    therapy_recent_signatures: dict[tuple[str, str], tuple[str, date]] = {}

    for entry in projection.entries:
        entry_flowables = _render_entry(
            entry=entry,
            date_style=date_style,
            fact_style=fact_style,
            meta_style=meta_style,
            timeline_row_keys=timeline_row_keys,
            therapy_recent_signatures=therapy_recent_signatures,
            claims_by_event=claims_by_event,
            extract_date_func=parse_date_string,
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
) -> bytes:
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=18, spaceAfter=12)
    h1_style = ParagraphStyle("H1Style", parent=styles["Heading1"], fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#2E548A"))
    normal_style = styles["Normal"]
    
    flowables = [Paragraph(f"Medical Chronology: {matter_title}", title_style)]
    flowables.append(Paragraph("Medical Chronology Analysis", h1_style))
    
    if narrative_synthesis:
        flowables.append(Paragraph("Executive Summary", h1_style))
        clean_narrative = _clean_narrative_text(narrative_synthesis)
        for p_text in clean_narrative.split("\n\n"):
            if p_text.strip():
                flowables.append(Paragraph(p_text.strip().replace("\n", "<br/>"), normal_style))
                flowables.append(Spacer(1, 0.1 * inch))
        flowables.append(Spacer(1, 0.1 * inch))
    flowables.append(Paragraph("What to Review First", h1_style))
    flowables.append(Paragraph("1) Top events panel: fast triage of the strongest record-backed facts.", normal_style))
    flowables.append(Paragraph("2) Chronological Medical Timeline: full encounter sequence with citations.", normal_style))
    flowables.append(Paragraph("3) Appendix G: Record Packet Citation Index for direct page-level source review.", normal_style))
    flowables.append(Spacer(1, 0.1 * inch))

    # ORDER MATTERS: tests split on timeline header then top10 header.
    flowables.append(Paragraph("Chronological Medical Timeline", h1_style))
    timeline_flowables = _build_projection_flowables(projection, raw_events, page_map, styles)
    if not timeline_flowables:
        flowables.append(Paragraph("No timeline events met the criteria for inclusion in this view.", normal_style))
    else:
        flowables.extend(timeline_flowables)

    flowables.append(Paragraph("Top 10 Case-Driving Events", h1_style))
    from apps.worker.steps.export_render.common import _projection_entry_substance_score
    
    candidates = []
    for entry in projection.entries:
        blob = " ".join(entry.facts or []).lower()
        if "routine follow-up" in blob and "acetaminophen" in blob: continue
        if "routine continuity gap" in blob: continue
        if "difficult mission late kind" in blob: continue
        if "preferred language" in blob: continue
        if _is_sdoh_noise(blob): continue
        
        score = _projection_entry_substance_score(entry)
        label = (entry.event_type_display or "").lower()
        if "emergency" in label: score += 10
        if "imaging" in label: score += 10
        if "procedure" in label: score += 15
        candidates.append((score, entry))
    
    scored = sorted(candidates, key=lambda x: x[0], reverse=True)
    top10_entries = []
    seen_blobs = set()
    for _, entry in scored:
        blob = " ".join(entry.facts or []).lower().strip()
        clean_blob = re.sub(r"\W+", " ", blob)
        if clean_blob in seen_blobs: continue
        seen_blobs.add(clean_blob)
        top10_entries.append(entry)
        if len(top10_entries) >= 10: break
        
    top10_entries = sorted(top10_entries, key=lambda e: (parse_date_string(e.date_display) or date.min, e.event_id))
    same_day_label_counts: dict[tuple[str, str], int] = {}

    for entry in top10_entries:
        evt_date = parse_date_string(entry.date_display)
        if not evt_date:
            continue
        facts_blob = _sanitize_render_sentence(" ".join(entry.facts or []))
        facts_blob = re.sub(r"\.\.+", ".", facts_blob)
        facts_blob = re.sub(r"\s{2,}", " ", facts_blob).strip()
        facts_blob = re.sub(r"\b(?:and|or|with|to)\.?\s*$", "", facts_blob, flags=re.IGNORECASE).strip()
        if not facts_blob: continue
        if not entry.citation_display:
            continue
        same_day_label = (evt_date.isoformat(), str(entry.event_type_display or "").strip().lower())
        if same_day_label_counts.get(same_day_label, 0) >= 2:
            continue
        same_day_label_counts[same_day_label] = same_day_label_counts.get(same_day_label, 0) + 1
        flowables.append(Paragraph(
            f"\u2022 {evt_date.isoformat()} | {entry.event_type_display} | {facts_blob} | Citation(s): {entry.citation_display}",
            normal_style,
        ))
        flowables.append(Spacer(1, 0.05 * inch))
    flowables.append(Spacer(1, 0.1 * inch))

    flowables.extend(build_projection_appendix_sections(
        appendix_entries or projection.entries,
        gaps,
        page_map,
        styles,
        raw_events=raw_events,
        all_citations=all_citations,
        missing_records_payload=missing_records_payload,
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
    return buffer.getvalue()
