"""
Step 12 — Export rendering (PDF + CSV + JSON).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone

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
)
from packages.shared.storage import save_artifact


def _date_str(event: Event) -> str:
    """Format event date for display."""
    d = event.date.value
    if isinstance(d, dict):
        return f"{d.get('start', '')} to {d.get('end', '')}"
    return str(d)


def _provider_name(event: Event, providers: list[Provider]) -> str:
    """Look up provider name for display."""
    for p in providers:
        if p.provider_id == event.provider_id:
            return p.normalized_name or p.detected_name_raw
    return "Unknown"


def _facts_text(event: Event) -> str:
    """Format facts as bullet list."""
    return "; ".join(f.text for f in event.facts)


def _pages_ref(event: Event) -> str:
    """Format page references."""
    return ", ".join(f"p. {p}" for p in sorted(event.source_page_numbers))


# ── PDF Export ────────────────────────────────────────────────────────────

def generate_pdf(
    run_id: str,
    matter_title: str,
    events: list[Event],
    gaps: list[Gap],
    providers: list[Provider],
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
            Paragraph("<b>Pages</b>", header_style),
        ]]

        for event in events:
            facts_bullets = "<br/>".join(f"• {f.text}" for f in event.facts[:6])
            table_data.append([
                Paragraph(str(event.date.sort_date()), fact_style),
                Paragraph(_provider_name(event, providers), fact_style),
                Paragraph(event.event_type.value.replace("_", " ").title(), fact_style),
                Paragraph(facts_bullets, fact_style),
                Paragraph(_pages_ref(event), fact_style),
            ])

        col_widths = [1.0 * inch, 1.3 * inch, 1.0 * inch, 3.0 * inch, 0.7 * inch]
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

def generate_csv(events: list[Event], providers: list[Provider]) -> bytes:
    """Generate a CSV chronology with one row per event."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "event_id", "date", "provider", "type", "confidence",
        "facts", "pages",
    ])

    for event in events:
        writer.writerow([
            event.event_id,
            str(event.date.sort_date()),
            _provider_name(event, providers),
            event.event_type.value,
            event.confidence,
            _facts_text(event),
            _pages_ref(event),
        ])

    return buf.getvalue().encode("utf-8")


# ── JSON Export ───────────────────────────────────────────────────────────

def generate_json(full_output: dict) -> bytes:
    """Serialize the full output to JSON bytes."""
    return json.dumps(full_output, indent=2, default=str).encode("utf-8")


# ── Export orchestrator ───────────────────────────────────────────────────

def render_exports(
    run_id: str,
    matter_title: str,
    events: list[Event],
    gaps: list[Gap],
    providers: list[Provider],
    full_output: dict,
) -> ChronologyOutput:
    """
    Render all export formats, save to disk, and return ChronologyOutput.
    """
    exported_ids = [e.event_id for e in events]

    # PDF
    pdf_bytes = generate_pdf(run_id, matter_title, events, gaps, providers)
    pdf_path = save_artifact(run_id, "chronology.pdf", pdf_bytes)
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()

    # CSV
    csv_bytes = generate_csv(events, providers)
    csv_path = save_artifact(run_id, "chronology.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()

    # JSON
    json_bytes = generate_json(full_output)
    json_path = save_artifact(run_id, "evidence_graph.json", json_bytes)
    json_sha = hashlib.sha256(json_bytes).hexdigest()

    return ChronologyOutput(
        export_format_version="0.1.0",
        events_exported=exported_ids,
        exports=ChronologyExports(
            pdf=ArtifactRef(uri=str(pdf_path), sha256=pdf_sha, bytes=len(pdf_bytes)),
            csv=ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes)),
            json_export=ArtifactRef(uri=str(json_path), sha256=json_sha, bytes=len(json_bytes)),
        ),
    )
