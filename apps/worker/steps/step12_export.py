"""
Step 12 — Export rendering (PDF + CSV + DOCX).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timezone

from docx import Document as DocxDocument
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from packages.shared.models import (
    ArtifactRef,
    CaseInfo,
    ChronologyExports,
    ChronologyOutput,
    Event,
    EventType,
    Gap,
    Provider,
    RunConfig,
    SourceDocument,
)
from packages.shared.storage import save_artifact


def _date_str(event: Event) -> str:
    """Format event date for display."""
    if not event.date:
        return ""
    
    ext = event.date.extensions or {}
    time_str = f" {ext['time']}" if ext.get("time") else ""

    # 1) Full date wins
    d = event.date.value
    if d:
        if isinstance(d, date):
            return f"{d.isoformat()}{time_str}"
        # DateRange object
        s = str(d.start)
        e = str(d.end) if d.end else ""
        return f"{s} to {e}{time_str}"
    
    # 2) Partial date via extensions (User Patch)
    if ext.get("partial_date") and ext.get("partial_month") and ext.get("partial_day"):
        # do NOT invent a year
        return f"{int(ext['partial_month']):02d}/{int(ext['partial_day']):02d} (year unknown){time_str}"

    # Fallback to model fields
    if event.date.partial_month is not None:
        return f"{event.date.partial_month:02d}/{event.date.partial_day:02d} (year unknown){time_str}"
    
    # 3) True relative day (positive) is allowed
    # STRICTLY positive only
    if event.date.relative_day is not None and event.date.relative_day >= 0:
        return f"Day {event.date.relative_day}{time_str}"
    
    return ""


def _provider_name(event: Event, providers: list[Provider]) -> str:
    """Look up provider name for display."""
    for p in providers:
        if p.provider_id == event.provider_id:
            return p.normalized_name or p.detected_name_raw
    return "Unknown"


def _facts_text(event: Event) -> str:
    """Format facts as bullet list."""
    return "; ".join(f.text for f in event.facts)



def _pages_ref(event: Event, page_map: dict[int, tuple[str, int]] | None = None) -> str:
    """Format page references with optional filenames."""
    if not page_map:
        return ", ".join(f"p. {p}" for p in sorted(event.source_page_numbers))
    
    # Resolve to filenames
    refs = []
    # Sort by global page number to keep order
    for p in sorted(event.source_page_numbers):
        if p in page_map:
            fname, local_p = page_map[p]
            refs.append(f"{fname} p. {local_p}")
        else:
            refs.append(f"p. {p}")
    
    # Deduplicate while preserving order?
    # Events usually on 1 page.
    return ", ".join(refs)


# ── PDF Export ────────────────────────────────────────────────────────────

def generate_pdf(
    run_id: str,
    matter_title: str,
    events: list[Event],
    gaps: list[Gap],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
    case_info: CaseInfo | None = None,
) -> bytes:
    """Generate a clean chronology PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    story = []

    story.append(Spacer(1, 0.5 * inch))

    # Executive Summary (New)
    if hasattr(events, "__iter__"): # Check if we have events
        from packages.shared.models import ChronologyOutput
        summary_text = generate_executive_summary(events, matter_title, case_info=case_info)
        
        summary_header_style = ParagraphStyle(
            "SummaryHeader", parent=styles["Heading2"], fontSize=14, spaceAfter=10, textColor=colors.HexColor("#2C3E50")
        )
        summary_body_style = ParagraphStyle(
            "SummaryBody", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=20, alignment=4 # Justified
        )
        
        story.append(Paragraph("Executive Case Summary", summary_header_style))
        story.append(Paragraph(summary_text.replace("\n", "<br/>"), summary_body_style))
        story.append(Spacer(1, 0.2 * inch))

    # Events table (Grouped by Date)
    if events:
        story.append(Paragraph("Clinical Timeline", styles["Heading2"]))
        story.append(Spacer(1, 0.1 * inch))

    # Events table (Chronological)
    if events:
        story.append(Paragraph("Clinical Timeline", styles["Heading2"]))
        story.append(Spacer(1, 0.1 * inch))

        fact_style = ParagraphStyle("FactStyle", parent=styles["Normal"], fontSize=8, leading=10)
        header_style = ParagraphStyle("HeaderStyle", parent=styles["Normal"], fontSize=9, textColor=colors.white)

        table_data = [[
            Paragraph("<b>Date/Time</b>", header_style),
            Paragraph("<b>Provider</b>", header_style),
            Paragraph("<b>Encounter Type</b>", header_style),
            Paragraph("<b>Clinical Facts & Findings</b>", header_style),
            Paragraph("<b>Source</b>", header_style),
        ]]

        sorted_events = sorted(events, key=lambda x: x.date.sort_key() if x.date else (99, "UNKNOWN"))
        
        for event in sorted_events:
            # Group facts with their specific citations if available
            fact_lines = []
            for f in event.facts[:12]:
                fact_lines.append(f"• {f.text}")
            
            facts_bullets = "<br/>".join(fact_lines)
            
            table_data.append([
                Paragraph(_date_str(event), fact_style),
                Paragraph(_provider_name(event, providers), fact_style),
                Paragraph(event.event_type.value.replace("_", " ").title(), fact_style),
                Paragraph(facts_bullets, fact_style),
                Paragraph(_pages_ref(event, page_map), fact_style),
            ])

        col_widths = [1.2 * inch, 1.2 * inch, 1.0 * inch, 2.6 * inch, 1.0 * inch]
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ECF0F1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9F9F9")]),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.2 * inch))

    # Gap appendix
    if gaps:
        story.append(Spacer(1, 0.5 * inch))
        story.append(Paragraph("<b>Appendix: Treatment Gaps</b>", styles["Heading2"]))
        for gap in gaps:
            story.append(Paragraph(
                f"• {gap.start_date} → {gap.end_date} ({gap.duration_days} days)",
                styles["Normal"],
            ))

    doc.build(story)
    return buf.getvalue()


# ── CSV Export ────────────────────────────────────────────────────────────

def generate_csv(
    events: list[Event],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
) -> bytes:
    """Generate a CSV chronology with one row per event."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "event_id", "date", "provider", "type", "confidence",
        "facts", "source_files",
    ])

    for event in events:
        date_display = _date_str(event)
        writer.writerow([
            event.event_id,
            date_display,
            _provider_name(event, providers),
            event.event_type.value,
            event.confidence,
            _facts_text(event),
            _pages_ref(event, page_map),
        ])

    return buf.getvalue().encode("utf-8")



# ── DOCX Export ──────────────────────────────────────────────────────────


def _set_cell_shading(cell, hex_color: str):
    """Set background shading on a DOCX table cell."""
    from docx.oxml.ns import qn
    from lxml import etree
    shading = etree.SubElement(cell._element.get_or_add_tcPr(), qn("w:shd"))
    shading.set(qn("w:fill"), hex_color)
    shading.set(qn("w:val"), "clear")


def generate_docx(
    run_id: str,
    matter_title: str,
    events: list[Event],
    gaps: list[Gap],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
) -> bytes:
    """
    Generate a professional DOCX chronology for paralegal use.

    Structure:
    - Title page with matter name and generation timestamp
    - Summary statistics
    - Chronology table (dated events sorted ascending)
    - Undated / Needs Review section
    - Treatment gaps appendix
    - Disclaimer
    """
    doc = DocxDocument()

    # ── Page setup ────────────────────────────────────────────────────
    for section in doc.sections:
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)

    # ── Title ─────────────────────────────────────────────────────────
    title_para = doc.add_heading("CiteLine Chronology", level=0)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    meta_lines = [
        f"Matter: {matter_title}",
        f"Run ID: {run_id}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    for line in meta_lines:
        p = doc.add_paragraph(line)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.runs[0].font.size = Pt(10)
        p.runs[0].font.color.rgb = RGBColor(0x7F, 0x8C, 0x8D)

    doc.add_paragraph()  # spacer

    # ── Partition events ──────────────────────────────────────────────
    dated_events = []
    undated_events = []
    flagged_events = []

    for evt in events:
        has_date = (
            evt.date is not None
            and evt.date.value is not None
        )
        needs_review = any(
            f in evt.flags
            for f in ("MISSING_DATE", "MISSING_SOURCE", "NEEDS_REVIEW", "LOW_CONFIDENCE")
        )

        if needs_review:
            flagged_events.append(evt)
        elif has_date:
            dated_events.append(evt)
        else:
            undated_events.append(evt)

    # Sort dated events ascending
    dated_events.sort(key=lambda e: e.date.sort_key() if e.date else (date.min, 0))

    # ── Summary statistics ────────────────────────────────────────────
    total = len(events)
    dated_count = len(dated_events)
    flagged_count = len(flagged_events)
    undated_count = len(undated_events)
    pct_dated = f"{(dated_count / total * 100):.0f}%" if total > 0 else "N/A"

    doc.add_heading("Summary", level=1)
    summary_table = doc.add_table(rows=4, cols=2)
    summary_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    stats = [
        ("Total Events", str(total)),
        ("Dated Events", f"{dated_count} ({pct_dated})"),
        ("Undated Events", str(undated_count)),
        ("Flagged (Needs Review)", str(flagged_count)),
    ]
    for i, (label, val) in enumerate(stats):
        summary_table.cell(i, 0).text = label
        summary_table.cell(i, 1).text = val
        for cell in (summary_table.cell(i, 0), summary_table.cell(i, 1)):
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(10)

    doc.add_paragraph()  # spacer

    # ── Helper: add events table ──────────────────────────────────────
    def _add_events_table(heading: str, event_list: list[Event]):
        if not event_list:
            return
        doc.add_heading(heading, level=1)

        tbl = doc.add_table(rows=1, cols=5)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = True

        # Header row
        headers = ["Date", "Provider", "Type", "Description", "Citation"]
        hdr_row = tbl.rows[0]
        for idx, hdr_text in enumerate(headers):
            cell = hdr_row.cells[idx]
            cell.text = hdr_text
            _set_cell_shading(cell, "2C3E50")
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.bold = True
                    run.font.size = Pt(9)
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # Data rows
        for evt in event_list:
            row = tbl.add_row()
            cells = row.cells
            cells[0].text = _date_str(evt)
            cells[1].text = _provider_name(evt, providers)
            cells[2].text = evt.event_type.value.replace("_", " ").title()

            # Description: first 6 facts as bullet points
            facts = "\n".join(f"• {f.text}" for f in evt.facts[:6])
            cells[3].text = facts

            # Citation
            cells[4].text = _pages_ref(evt, page_map)

            # Style data cells
            for cell in cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(8)

    # ── Dated events table ────────────────────────────────────────────
    _add_events_table("Chronology", dated_events)

    # ── Undated / Needs Review ────────────────────────────────────────
    review_events = undated_events + flagged_events
    if review_events:
        _add_events_table("Undated / Needs Review", review_events)

        # Add flags detail
        doc.add_paragraph()
        for evt in flagged_events:
            flags_str = ", ".join(evt.flags) if evt.flags else "UNDATED"
            p = doc.add_paragraph(f"⚠ {evt.event_id}: {flags_str}", style="List Bullet")
            for run in p.runs:
                run.font.size = Pt(8)
                run.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)

    # ── Treatment gaps ────────────────────────────────────────────────
    if gaps:
        doc.add_heading("Appendix: Treatment Gaps", level=1)
        for gap in gaps:
            doc.add_paragraph(
                f"• {gap.start_date} → {gap.end_date} ({gap.duration_days} days)",
                style="List Bullet",
            )

    # ── Disclaimer ────────────────────────────────────────────────────
    doc.add_paragraph()
    disclaimer = doc.add_paragraph(
        "Factual extraction with citations. Requires human review. "
        "This document does not constitute legal or medical advice."
    )
    for run in disclaimer.runs:
        run.font.size = Pt(8)
        run.font.italic = True
        run.font.color.rgb = RGBColor(0x7F, 0x8C, 0x8D)

    # ── Serialize ─────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── Export orchestrator ───────────────────────────────────────────────────

def render_exports(
    run_id: str,
    matter_title: str,
    events: list[Event],
    gaps: list[Gap],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
    case_info: CaseInfo | None = None,
) -> ChronologyOutput:
    """
    Render all export formats, save to disk, and return ChronologyOutput.
    """
    exported_ids = [e.event_id for e in events]

    # PDF
    pdf_bytes = generate_pdf(run_id, matter_title, events, gaps, providers, page_map, case_info=case_info)
    pdf_path = save_artifact(run_id, "chronology.pdf", pdf_bytes)
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()

    # CSV
    csv_bytes = generate_csv(events, providers, page_map)
    csv_path = save_artifact(run_id, "chronology.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()

    # DOCX
    docx_bytes = generate_docx(run_id, matter_title, events, gaps, providers, page_map)
    docx_path = save_artifact(run_id, "chronology.docx", docx_bytes)
    docx_sha = hashlib.sha256(docx_bytes).hexdigest()

    # Summary
    summary_text = generate_executive_summary(events, matter_title, case_info=case_info)

    return ChronologyOutput(
        export_format_version="0.1.0",
        summary=summary_text,
        events_exported=exported_ids,
        exports=ChronologyExports(
            pdf=ArtifactRef(uri=str(pdf_path), sha256=pdf_sha, bytes=len(pdf_bytes)),
            csv=ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes)),
            docx=ArtifactRef(uri=str(docx_path), sha256=docx_sha, bytes=len(docx_bytes)),
            json_export=None,
        ),
    )


def generate_executive_summary(events: list[Event], matter_title: str, case_info: CaseInfo | None = None) -> str:
    """Generate a high-level narrative summary of the chronology."""
    if not events:
        return "No events documented."
    
    # Filter to dated events for the range calculation, excluding references
    dated_events = [
        e for e in events 
        if e.date and e.date.sort_key()[0] < 99 
        and e.event_type != EventType.REFERENCED_PRIOR_EVENT
        and "is_reference" not in (e.flags or [])
    ]
    if not dated_events:
        return "No dated events documented."
    
    # Sort by the robust sort_key
    dated_events.sort(key=lambda e: e.date.sort_key())
    
    summary = f"Summary for {matter_title}:\n\n"

    # Patient Header Information
    if case_info and case_info.patient:
        p = case_info.patient
        # Extract name from matter title or case info? matter_title usually has it
        summary += f"Patient Name: {matter_title.split('-')[0].strip()}\n"
        if p.age:
            summary += f"Age: {p.age}\n"
        
        # Try to find diagnosis in facts first, then fallback
        diagnosis = None
        for e in events:
            for f in e.facts:
                if "Diagnosis:" in f.text:
                    diagnosis = f.text.split(":", 1)[1].strip()
                    break
                if "Medical History:" in f.text and not diagnosis:
                    diagnosis = f.text.split(":", 1)[1].strip()
            if diagnosis: break
        
        if diagnosis:
            # Clean up: remove "Patient is a 65-year-old female with a four-year history of "
            diagnosis = re.sub(r"(?i)Patient is a \d+-year-old [^ ]+ with a [^ ]+ history of ", "", diagnosis)
            summary += f"Diagnosis: {diagnosis.capitalize()}\n"
        summary += "\n"
    
    # Heuristic: Find first major admission, first procedure, and last discharge or status
    admissions = [e for e in dated_events if e.event_type == EventType.HOSPITAL_ADMISSION]
    discharges = [e for e in dated_events if e.event_type in (EventType.HOSPITAL_DISCHARGE, EventType.DISCHARGE)]
    procedures = [e for e in dated_events if e.event_type == EventType.PROCEDURE]
    
    # DEBUG
    # print(f"DEBUG SUMMARY: dated_events={len(dated_events)} admissions={len(admissions)} discharges={len(discharges)}")
    
    if admissions:
        first_adm = sorted(admissions, key=lambda e: e.date.sort_key())[0]
        summary += f"Documented care began with a hospital admission on {_date_str(first_adm)}. "
    else:
        summary += f"Medical records begin on {_date_str(dated_events[0])}. "
        
    if procedures:
        p_count = len(procedures)
        summary += f"The clinical course included {p_count} significant procedures or operations. "
        
    if discharges:
        # Sort by sort_key DESC to find latest
        sorted_dis = sorted(discharges, key=lambda e: e.date.sort_key(), reverse=True)
        last_dis = sorted_dis[0]
        # print(f"DEBUG SUMMARY: latest discharge event: date={_date_str(last_dis)} type={last_dis.event_type}")
        summary += f"The latest documented discharge occurred on {_date_str(last_dis)}. "
    else:
        summary += f"The records conclude on {_date_str(dated_events[-1])}. "
        
    # Mention specific indicators found?
    pain_facts = []
    functional_facts = []
    diagnosis_facts = []
    history_facts = []
    for e in events:
        for f in e.facts:
            if "Pain Level:" in f.text:
                pain_facts.append(f.text)
            if "Functional Status:" in f.text:
                functional_facts.append(f.text)
            if "Diagnosis:" in f.text:
                diagnosis_facts.append(f.text)
            if "Medical History:" in f.text:
                history_facts.append(f.text)
    
    if history_facts and not diagnosis_facts:
        summary += f"\n\nRelevant medical history includes {history_facts[0].split(':')[-1].strip()}. "

    if pain_facts:
        highlights = pain_facts[0].split(":")[-1].strip()
        summary += f"\n\nKey highlights include reports of significant pain ({highlights}). "
    
    if functional_facts:
        summary += f"Functional decline or assistance requirements were noted, including: {functional_facts[0].split(':')[-1].strip()}. "
        
    # Add Assessment Findings (New)
    findings = {}
    for e in events:
        if e.extensions and "assessment_findings" in e.extensions:
            findings = e.extensions["assessment_findings"]
            break
            
    if findings:
        summary += "\n\nKey Assessment Findings:\n"
        if "fall_risk" in findings:
            summary += f"- Safety: High fall risk (Score: {findings['fall_risk']}); requires assistance for ambulation.\n"
        if "edema" in findings:
            summary += f"- Physical: {findings['edema']} noted.\n"
        if "kyphosis" in findings:
            summary += f"- Physical: Kyphosis of the spine noted.\n"
        if "weight_history" in findings:
            summary += f"- Weight: Weight history: {findings['weight_history']}.\n"

    summary += "\n\nRefer to the timeline below for a complete clinical history with citations."
    return summary
