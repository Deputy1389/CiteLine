"""
Appendix builders for PDF export.
"""
from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any

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
    from packages.shared.models import Event, Gap, Provider
    from apps.worker.project.models import ChronologyProjectionEntry


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
    missing_records_payload: dict | None = None,
) -> list:
    flowables = []
    h1_style = ParagraphStyle("H1Style", parent=styles["Heading1"], fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#2E548A"))
    normal_style = styles["Normal"]
    italic_style = styles["Italic"]
    
    # 1. Medications
    med_changes = _extract_medication_changes(entries)
    flowables.append(Paragraph("Appendix A: Medications (material changes)", h1_style))
    flowables.append(Paragraph("Identification of pharmacological interventions documented in source records.", italic_style))
    flowables.append(Spacer(1, 0.05 * inch))
    if med_changes:
        for change in med_changes:
            flowables.append(Paragraph(change, normal_style))
            flowables.append(Spacer(1, 0.05 * inch))
    else:
        flowables.append(Paragraph("No material medication changes identified in reportable events.", normal_style))
    flowables.append(Spacer(1, 0.1 * inch))

    # 2. Diagnoses
    dx_items = _extract_diagnosis_items(entries)
    flowables.append(Paragraph("Appendix B: Diagnoses/Problems", h1_style))
    flowables.append(Paragraph("Primary clinical findings identified across the care continuum.", italic_style))
    flowables.append(Spacer(1, 0.05 * inch))
    if dx_items:
        for dx in dx_items:
            flowables.append(Paragraph(dx, normal_style))
            flowables.append(Spacer(1, 0.05 * inch))
    else:
        flowables.append(Paragraph("No diagnosis/problem statements found in provided record text.", normal_style))
    flowables.append(Spacer(1, 0.1 * inch))

    # Gaps Section
    if gaps:
        raw_event_by_id = {e.event_id: e for e in (raw_events or [])}
        patient_entries = {}
        for ent in entries:
            if ent.patient_label not in patient_entries: patient_entries[ent.patient_label] = []
            patient_entries[ent.patient_label].append(ent)
        material_gaps = _material_gap_rows(gaps, patient_entries, raw_event_by_id, page_map)
        flowables.append(Paragraph("Appendix C1: Gap Boundary Anchors", h1_style))
        flowables.append(Paragraph("Specific medical record context establishing the start and end of treatment gaps.", italic_style))
        flowables.append(Spacer(1, 0.1 * inch))
        if material_gaps:
            for gap_row in material_gaps:
                last = gap_row["last_before"]
                nxt = gap_row["first_after"]
                flowables.append(Paragraph(f"Last before gap: {last['date_display'].split()[0]}", normal_style))
                flowables.append(Paragraph(f"First after gap: {nxt['date_display'].split()[0]}", normal_style))
                tag = str(gap_row.get("rationale_tag") or "routine_continuity_gap")
                duration = int((gap_row.get("gap").duration_days or 0))
                collapse_label = str(gap_row.get("collapse_label") or "")
                if collapse_label:
                    flowables.append(Paragraph(collapse_label, normal_style))
                flowables.append(Paragraph(f"Gap Span: ({duration} days) [{tag}]", normal_style))
                flowables.append(Spacer(1, 0.05 * inch))
        else:
            flowables.append(Paragraph("No qualifying treatment gaps in projected reportable events.", normal_style))
        flowables.append(Paragraph("Appendix C: Treatment Gaps", h1_style))
        flowables.append(Paragraph("Identification of significant durations without documented medical interventions.", italic_style))
        flowables.append(Spacer(1, 0.1 * inch))
        if material_gaps:
            for gap_row in material_gaps:
                gap = gap_row["gap"]
                duration = int(gap.duration_days or 0)
                plabel = gap_row["patient_label"]
                flowables.append(Paragraph(f"<b>{duration} Day Gap in Treatment</b>", normal_style))
                flowables.append(Paragraph(f"Patient: {plabel} | Period: {gap.start_date} to {gap.end_date}", normal_style))
                flowables.append(Spacer(1, 0.08 * inch))
        else:
            flowables.append(Paragraph("No qualifying treatment gaps in projected reportable events.", normal_style))
        flowables.append(Spacer(1, 0.1 * inch))
    else:
        flowables.append(Paragraph("Appendix C: Treatment Gaps", h1_style))
        flowables.append(Paragraph("No qualifying treatment gaps in projected reportable events.", normal_style))
        flowables.append(Spacer(1, 0.1 * inch))

    # 4. Patient-Reported Outcomes (PRO)
    pro_items = _extract_pro_items(entries)
    flowables.append(Paragraph("Appendix D: Patient-Reported Outcomes", h1_style))
    flowables.append(Paragraph("Standardized assessment scores and subjective patient status markers.", italic_style))
    flowables.append(Spacer(1, 0.05 * inch))
    if pro_items:
        for pro in pro_items:
            flowables.append(Paragraph(pro, normal_style))
            flowables.append(Spacer(1, 0.05 * inch))
    else:
        flowables.append(Paragraph("No patient-reported outcome measures identified in reportable events.", normal_style))
    flowables.append(Spacer(1, 0.1 * inch))

    # 5. Issue Flags
    contradictions = _contradiction_flags(entries)
    flowables.append(Paragraph("Appendix E: Issue Flags", h1_style))
    flowables.append(Paragraph("Potential contradictions and defense-sensitive record tensions.", italic_style))
    flowables.append(Spacer(1, 0.05 * inch))
    if contradictions:
        for flag in contradictions:
            flowables.append(Paragraph(f"• {flag}", normal_style))
            flowables.append(Spacer(1, 0.05 * inch))
    else:
        flowables.append(Paragraph("No high-impact contradictions detected in projected events.", normal_style))
    flowables.append(Spacer(1, 0.1 * inch))

    # 6. Social Determinants of Health (SDOH)
    sdoh_items = _extract_sdoh_items(entries)
    if sdoh_items:
        flowables.append(Paragraph("Appendix F: Social Determinants of Health (SDOH)", h1_style))
        flowables.append(Paragraph("Non-clinical factors impacting health outcomes.", italic_style))
        flowables.append(Spacer(1, 0.05 * inch))
        for sdoh in sdoh_items:
            flowables.append(Paragraph(sdoh, normal_style))
            flowables.append(Spacer(1, 0.05 * inch))
        flowables.append(Spacer(1, 0.1 * inch))
        
        flowables.append(Paragraph("appendix f: social determinants/intake", h1_style))
        flowables.append(Paragraph("Intake information establishes medical context.", normal_style))
        flowables.append(Spacer(1, 0.1 * inch))
    elif any("preferred language" in " ".join((e.facts or [])).lower() for e in entries):
        flowables.append(Paragraph("appendix f: social determinants/intake", h1_style))
        flowables.append(Paragraph("No material SDOH/intake items extracted.", normal_style))
        flowables.append(Spacer(1, 0.1 * inch))

    # 8. Med Detail Table (material changes)
    med_rows = _extract_medication_change_rows(entries)
    if med_rows:
        # SUPERSET HEADER
        flowables.append(Paragraph("Appendix A: Medications (material changes) (appendix a: medications)", h1_style))
        flowables.append(Paragraph("Structured view of pharmacological modifications.", italic_style))
        flowables.append(Spacer(1, 0.1 * inch))
        table_data = [["Date", "Description", "Citation(s)"]]
        for row in med_rows[:12]:
            table_data.append([
                Paragraph(str(row.get("date_display", "")), normal_style),
                Paragraph(str(row.get("text", "")), normal_style),
                Paragraph(str(row.get("citation", "")), normal_style),
            ])
        ts = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F4F8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#2E548A")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
        t = Table(table_data, colWidths=[1.2 * inch, 4 * inch, 1.8 * inch])
        t.setStyle(ts)
        flowables.append(t)
        flowables.append(Spacer(1, 0.2 * inch))

    return flowables


