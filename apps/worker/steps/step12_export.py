"""
Step 12 — Export rendering (PDF + CSV + DOCX).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
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
    
    d = event.date.value
    if d:
        if isinstance(d, dict):
            return f"{d.get('start', '')} to {d.get('end', '')}"
        if isinstance(d, date):
            return str(d)
        # DateRange object
        s = str(d.start)
        e = str(d.end) if d.end else ""
        return f"{s} to {e}"
    
    if event.date.relative_day is not None:
        return f"Day {event.date.relative_day}"
    
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
) -> bytes:
    """Generate a clean chronology PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    story = []

    # Title page
    title_style = ParagraphStyle(
        "TitlePage", parent=styles["Title"], fontSize=24, spaceAfter=20,
    )
    story.append(Spacer(1, 1.5 * inch))
    story.append(Paragraph("CiteLine Chronology", title_style))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(f"<b>Matter:</b> {matter_title}", styles["Normal"]))
    story.append(Paragraph(f"<b>Run ID:</b> {run_id}", styles["Normal"]))
    story.append(Paragraph(
        f"<b>Generated:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.5 * inch))

    disclaimer_style = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"], fontSize=9,
        textColor=colors.grey, spaceAfter=20,
    )
    story.append(Paragraph(
        "<i>Factual extraction with citations. Requires human review. "
        "This document does not constitute legal or medical advice.</i>",
        disclaimer_style,
    ))
    story.append(Spacer(1, 0.5 * inch))

    # Events table
    if events:
        fact_style = ParagraphStyle("FactStyle", parent=styles["Normal"], fontSize=8, leading=10)
        header_style = ParagraphStyle("HeaderStyle", parent=styles["Normal"], fontSize=9, textColor=colors.white)

        table_data = [[
            Paragraph("<b>Date</b>", header_style),
            Paragraph("<b>Provider</b>", header_style),
            Paragraph("<b>Type</b>", header_style),
            Paragraph("<b>Key Facts</b>", header_style),
            Paragraph("<b>Source</b>", header_style),
        ]]

        for event in events:
            facts_bullets = "<br/>".join(f"• {f.text}" for f in event.facts[:6])
            table_data.append([
                Paragraph(str(event.date.sort_date()), fact_style),
                Paragraph(_provider_name(event, providers), fact_style),
                Paragraph(event.event_type.value.replace("_", " ").title(), fact_style),
                Paragraph(facts_bullets, fact_style),
                Paragraph(_pages_ref(event, page_map), fact_style),
            ])

        col_widths = [1.0 * inch, 1.3 * inch, 1.0 * inch, 2.2 * inch, 1.5 * inch]
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)

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
        writer.writerow([
            event.event_id,
            str(event.date.sort_date()),
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
) -> ChronologyOutput:
    """
    Render all export formats, save to disk, and return ChronologyOutput.
    """
    exported_ids = [e.event_id for e in events]

    # PDF
    pdf_bytes = generate_pdf(run_id, matter_title, events, gaps, providers, page_map)
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

    return ChronologyOutput(
        export_format_version="0.1.0",
        events_exported=exported_ids,
        exports=ChronologyExports(
            pdf=ArtifactRef(uri=str(pdf_path), sha256=pdf_sha, bytes=len(pdf_bytes)),
            csv=ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes)),
            docx=ArtifactRef(uri=str(docx_path), sha256=docx_sha, bytes=len(docx_bytes)),
            json_export=None,
        ),
    )
