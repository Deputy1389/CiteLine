"""
Settlement Posture PDF renderer — renders the "Settlement Intelligence" page.

Receives only pre-extracted dicts from extensions. No clinical keywords here —
all medical signal extraction happened upstream in apps/worker/lib/.

Public API:
    render_settlement_posture_page(
        run_id, settlement_model_report, defense_attack_map, case_severity_index
    ) -> bytes | None

Returns PDF bytes for the settlement intelligence page, or None on failure.
The caller (orchestrator) is responsible for appending these bytes to the main PDF.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# ── Layout constants ──────────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter
MARGIN = 0.65 * inch
CONTENT_W = PAGE_W - 2 * MARGIN

# ── Brand colours (no clinical content) ──────────────────────────────────────
_DARK_NAVY = colors.HexColor("#1a2a4a")
_MID_BLUE = colors.HexColor("#2563eb")
_LIGHT_BLUE = colors.HexColor("#dbeafe")
_DANGER_RED = colors.HexColor("#dc2626")
_WARN_AMBER = colors.HexColor("#d97706")
_OK_GREEN = colors.HexColor("#16a34a")
_RULE_GREY = colors.HexColor("#e2e8f0")
_TEXT_GREY = colors.HexColor("#374151")
_LIGHT_GREY_BG = colors.HexColor("#f8fafc")

_SEVERITY_COLOURS: dict[str, Any] = {
    "HIGH": _DANGER_RED,
    "MED": _WARN_AMBER,
    "LOW": colors.HexColor("#6b7280"),
}

# ── Style factory ─────────────────────────────────────────────────────────────

def _make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()

    return {
        "page_title": ParagraphStyle(
            "page_title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=_DARK_NAVY,
            spaceAfter=2,
        ),
        "page_subtitle": ParagraphStyle(
            "page_subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=8,
        ),
        "section_header": ParagraphStyle(
            "section_header",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=_DARK_NAVY,
            spaceBefore=10,
            spaceAfter=3,
            leading=12,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            textColor=_TEXT_GREY,
            leftIndent=10,
            spaceAfter=2,
            leading=12,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            textColor=_TEXT_GREY,
            spaceAfter=4,
            leading=12,
        ),
        "flag_label": ParagraphStyle(
            "flag_label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            textColor=_DARK_NAVY,
            leading=12,
            spaceAfter=1,
        ),
        "flag_body": ParagraphStyle(
            "flag_body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            textColor=colors.HexColor("#4b5563"),
            leading=10,
            leftIndent=12,
            spaceAfter=2,
        ),
        "score_label": ParagraphStyle(
            "score_label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=_DARK_NAVY,
            leading=14,
        ),
        "score_value": ParagraphStyle(
            "score_value",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=_MID_BLUE,
            leading=24,
        ),
        "posture_label": ParagraphStyle(
            "posture_label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=_DARK_NAVY,
            leading=14,
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=6.5,
            textColor=colors.HexColor("#94a3b8"),
            leading=9,
            spaceAfter=0,
        ),
    }


# ── Section builders ──────────────────────────────────────────────────────────

def _header_table(
    smr: dict,
    dam: dict | None,
    csi: dict | None,
    styles: dict,
) -> list:
    """Top banner with title, CSI score, and posture label."""
    csi_val = (csi or {}).get("case_severity_index")
    posture = smr.get("recommended_posture") or "BUILD_CASE"
    sli = smr.get("settlement_leverage_index")

    csi_text = f"{csi_val}/10" if csi_val is not None else "—"
    sli_text = f"SLI: {sli:.2f}" if sli is not None else ""

    left_cell = [
        Paragraph("SETTLEMENT INTELLIGENCE", styles["page_title"]),
        Paragraph(
            f"Deterministic advisory report — for attorney review only   {sli_text}",
            styles["page_subtitle"],
        ),
    ]
    right_cell = [
        Paragraph("Case Severity Index", styles["score_label"]),
        Paragraph(csi_text, styles["score_value"]),
        Paragraph(posture.replace("_", " "), styles["posture_label"]),
    ]

    tbl = Table(
        [[left_cell, right_cell]],
        colWidths=[CONTENT_W * 0.65, CONTENT_W * 0.35],
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_GREY_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, _RULE_GREY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [tbl, Spacer(1, 8)]


def _strengths_section(strengths: list[str], styles: dict) -> list:
    elems: list = []
    if not strengths:
        return elems
    elems.append(Paragraph("STRENGTHS", styles["section_header"]))
    for s in strengths:
        elems.append(Paragraph(f"\u2022  {s}", styles["bullet"]))
    return elems


def _risk_factors_section(risk_factors: list[str], styles: dict) -> list:
    elems: list = []
    if not risk_factors:
        return elems
    elems.append(Paragraph("RISK FACTORS", styles["section_header"]))
    for r in risk_factors:
        elems.append(Paragraph(f"\u25B6  {r}", styles["bullet"]))
    return elems


def _posture_section(smr: dict, styles: dict) -> list:
    posture_text = smr.get("posture_text") or ""
    if not posture_text:
        return []
    elems: list = [
        Paragraph("NEGOTIATION POSTURE", styles["section_header"]),
        Paragraph(posture_text, styles["body"]),
    ]
    return elems


def _dam_section(dam: dict | None, styles: dict, max_flags: int = 4) -> list:
    if not isinstance(dam, dict):
        return []
    triggered = [
        f for f in (dam.get("flags") or [])
        if isinstance(f, dict) and f.get("triggered")
    ]
    if not triggered:
        return []

    elems: list = [Paragraph("DEFENSE ATTACK VECTORS", styles["section_header"])]

    # Sort by severity: HIGH first
    _sev_order = {"HIGH": 0, "MED": 1, "LOW": 2}
    triggered_sorted = sorted(
        triggered, key=lambda f: _sev_order.get(f.get("severity", "MED"), 1)
    )

    for i, flag in enumerate(triggered_sorted[:max_flags]):
        sev = flag.get("severity", "MED")
        sev_colour = _SEVERITY_COLOURS.get(sev, _TEXT_GREY)
        label = flag.get("label", "")
        detail = flag.get("detail", "")
        defense = flag.get("defense_argument", "")
        counter = flag.get("plaintiff_counter", "")

        num = "\u2460\u2461\u2462\u2463"[i] if i < 4 else f"{i+1}."

        # Flag header row
        header_data = [[
            Paragraph(
                f"{num}  <font color='#{sev_colour.hexval()[2:]}'>[{sev}]</font>  {label}",
                styles["flag_label"],
            )
        ]]
        flag_rows: list = []
        if detail:
            flag_rows.append(Paragraph(detail, styles["flag_body"]))
        if defense:
            flag_rows.append(
                Paragraph(f"<b>Defense:</b> \"{defense}\"", styles["flag_body"])
            )
        if counter:
            flag_rows.append(
                Paragraph(f"<b>Counter:</b> {counter}", styles["flag_body"])
            )

        tbl = Table(
            [
                [Paragraph(
                    f"{num}  {label}  <font color='#{sev_colour.hexval()[2:]}' size='7'>[{sev}]</font>",
                    styles["flag_label"],
                )],
                *[[r] for r in flag_rows],
            ],
            colWidths=[CONTENT_W],
        )
        tbl.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.3, _RULE_GREY),
            ("BACKGROUND", (0, 0), (-1, 0), _LIGHT_GREY_BG),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elems.append(tbl)
        elems.append(Spacer(1, 4))

    remaining = len(triggered) - max_flags
    if remaining > 0:
        elems.append(
            Paragraph(
                f"+ {remaining} additional risk factor(s) not shown.",
                styles["flag_body"],
            )
        )
    return elems


def _disclaimer_section(styles: dict) -> list:
    return [
        Spacer(1, 8),
        Paragraph(
            "This settlement intelligence report is generated deterministically from "
            "structured medical record data. It is advisory only and does not constitute "
            "legal advice. All figures and assessments should be reviewed by qualified "
            "legal counsel before use in negotiations.",
            styles["disclaimer"],
        ),
    ]


# ── Page frame setup ──────────────────────────────────────────────────────────

def _on_page(canvas, doc) -> None:
    """Draw page border and footer."""
    canvas.saveState()
    canvas.setStrokeColor(_RULE_GREY)
    canvas.setLineWidth(0.5)
    canvas.rect(MARGIN * 0.5, MARGIN * 0.5, PAGE_W - MARGIN, PAGE_H - MARGIN)

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#94a3b8"))
    canvas.drawRightString(
        PAGE_W - MARGIN,
        MARGIN * 0.4,
        f"Settlement Intelligence  |  Page {doc.page}  |  Citeline Advisory",
    )
    canvas.restoreState()


# ── Public renderer ───────────────────────────────────────────────────────────

def render_settlement_posture_page(
    run_id: str,
    settlement_model_report: dict | None,
    defense_attack_map: dict | None,
    case_severity_index: dict | None,
) -> bytes | None:
    """
    Render the Settlement Intelligence PDF page.

    All inputs are pre-extracted dicts from extensions. No clinical keywords here.

    Parameters
    ----------
    run_id
        Run identifier (used for logging only).
    settlement_model_report
        SettlementModelReport.v1 dict or None.
    defense_attack_map
        DefenseAttackMap.v2 dict or None.
    case_severity_index
        CSI.v1 dict or None.

    Returns
    -------
    bytes | None
        Raw PDF bytes for the settlement page, or None if rendering fails.
    """
    try:
        smr: dict = settlement_model_report if isinstance(settlement_model_report, dict) else {}
        dam: dict | None = defense_attack_map if isinstance(defense_attack_map, dict) else None
        csi: dict | None = case_severity_index if isinstance(case_severity_index, dict) else None

        styles = _make_styles()

        # Build story
        story: list = []
        story.extend(_header_table(smr, dam, csi, styles))

        # Two-column layout: strengths left, risk factors right
        strengths = smr.get("strengths") or []
        risk_factors = smr.get("risk_factors") or []

        if strengths or risk_factors:
            left_elems = _strengths_section(strengths, styles)
            right_elems = _risk_factors_section(risk_factors, styles)

            # Pad shorter column
            while len(left_elems) < len(right_elems):
                left_elems.append(Spacer(1, 1))
            while len(right_elems) < len(left_elems):
                right_elems.append(Spacer(1, 1))

            if left_elems or right_elems:
                tbl = Table(
                    [[left_elems or [Spacer(1, 1)], right_elems or [Spacer(1, 1)]]],
                    colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5],
                )
                tbl.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]))
                story.append(tbl)

        story.extend(_posture_section(smr, styles))
        story.extend(_dam_section(dam, styles))
        story.extend(_disclaimer_section(styles))

        # Render to bytes
        buf = io.BytesIO()
        frame = Frame(MARGIN, MARGIN, CONTENT_W, PAGE_H - 2 * MARGIN, id="body")
        doc = BaseDocTemplate(
            buf,
            pagesize=letter,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN,
            bottomMargin=MARGIN,
        )
        template = PageTemplate(id="settlement_page", frames=[frame], onPage=_on_page)
        doc.addPageTemplates([template])
        doc.build(story)

        return buf.getvalue()

    except Exception as exc:
        logger.exception(f"settlement_posture_pdf render failed for run {run_id}: {exc}")
        return None
