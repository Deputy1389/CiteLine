"""
Timeline rendering logic for PDF export.
"""
from __future__ import annotations

import re
import logging
from datetime import date
from io import BytesIO
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

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
    Table,
    TableStyle,
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
    is_sentinel_date,
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
    from apps.worker.steps.export_render.extraction_utils import _scan_incident_signal, _refine_primary_injuries
    from apps.worker.steps.events.clinical_extraction import canonicalize_injuries
    from apps.worker.steps.events.billing import _extract_amount

    page_text: dict[int, str] = {}
    all_facts = []
    total_charges = 0.0
    for e in events:
        facts = [f.text or "" for f in e.facts]
        all_facts.extend(facts)
        for p in (e.source_page_numbers or []):
            if p not in page_text:
                page_text[p] = " ".join(facts)
        if e.billing and e.billing.total_amount:
            total_charges += e.billing.total_amount

    incident = _scan_incident_signal(page_text, None)
    summary = f"Executive Summary for {matter_title}\n\n"

    summary += "--- INCIDENT & DOI ---\n"
    if incident.get("found"):
        summary += f"Date of Injury: {incident['doi'] or 'Not established'}\n"
        summary += f"Mechanism: {incident['mechanism'] or 'Not established'}\n"
    else:
        summary += "Incident details not established from available records.\n"

    summary += "\n--- PRIMARY INJURIES ---\n"
    injuries = canonicalize_injuries(set(all_facts))
    # Filter for high-signal injury keywords
    injury_keywords = {"fracture", "dislocation", "tear", "strain", "sprain", "herniation", "protrusion", "stenosis", "radiculopathy"}
    detected_injuries = [inj for inj in injuries if any(kw in inj.lower() for kw in injury_keywords)]
    if detected_injuries:
        refined = _refine_primary_injuries(detected_injuries, events)
        summary += f"Key Clinical Findings: {', '.join(refined[:8])}\n"
    else:
        summary += "Specific injury diagnosis not clearly labeled in extracted problem list.\n"

    summary += "\n--- BILLING SUMMARY ---\n"
    if total_charges > 0:
        summary += f"Total Identified Medical Charges: ${total_charges:,.2f}\n"
        summary += "See 'Specials & Medical Billing Summary' section for detailed breakdown.\n"
    else:
        summary += "Medical billing totals not available from extracted records.\n"

    summary += f"\nTotal encounters analyzed: {len(events)}\n"
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
            select_timeline=getattr(projection, "select_timeline", True),
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


_FRONT_PAGE_BANNED_PHRASES = (
    "no specific traumatic injuries isolated",
    "soft tissue only",
    "no injury",
)


def _ext_payload(evidence_graph_payload: dict | None) -> dict:
    if not isinstance(evidence_graph_payload, dict):
        return {}
    if isinstance(evidence_graph_payload.get("extensions"), dict):
        return evidence_graph_payload.get("extensions") or {}
    eg = (((evidence_graph_payload.get("outputs") or {}).get("evidence_graph")) or {})
    if isinstance(eg, dict) and isinstance(eg.get("extensions"), dict):
        return eg.get("extensions") or {}
    return {}


def _clean_line(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", str(text)).strip()
    text = re.sub(r"^\W+", "", text)
    return text[:500]


def _attorney_placeholder_text(text: str | None) -> str:
    s = _clean_line(text)
    if not s:
        return ""
    low = s.lower()
    if low == "see patient header":
        return "Patient name not reliably extracted from packet"
    return s


def _is_undermining_or_noise(text: str) -> bool:
    blob = (text or "").lower()
    if not blob:
        return True
    if any(p in blob for p in _FRONT_PAGE_BANNED_PHRASES):
        return True
    if "(cid:" in blob:
        return True
    if len(blob.split()) < 3:
        return True
    return False


def _has_supported_disc_injury(ext: dict, raw_events: list[Event] | None) -> bool:
    patterns = re.compile(r"\b(disc|radiculopathy|foramen|foraminal|herniat|protrusion|stenosis)\b", re.I)
    for row in (ext.get("claim_rows") or []):
        if patterns.search(str(row.get("assertion") or "")):
            return True
    for evt in raw_events or []:
        for fact in list(getattr(evt, "facts", []) or []) + list(getattr(evt, "diagnoses", []) or []) + list(getattr(evt, "exam_findings", []) or []):
            if patterns.search(str(getattr(fact, "text", "") or "")):
                return True
    return False


def _guardrail_text(text: str, *, supported_injury: bool) -> str:
    out = text or ""
    low = out.lower()
    for banned in _FRONT_PAGE_BANNED_PHRASES:
        if banned in low:
            if supported_injury:
                return "Injury characterization varies across notes; objective findings are summarized below."
            return ""
    return out


def _event_date_label(event: Event) -> str:
    try:
        label = _date_str(event)
    except Exception:
        return "Undated"
    label = re.sub(r"\s*\(time not documented\)\s*", "", label or "").strip()
    return label or "Undated"


def _attorney_date_display(label: str | None) -> str:
    s = _attorney_placeholder_text(label)
    if not s:
        return "Undated"
    s = re.sub(r"\s*\(time not documented\)\s*", "", s, flags=re.I).strip()
    if is_sentinel_date(s):
        return "Undated"
    return s or "Undated"


def _event_date_bounds(event: Event) -> tuple[date | None, date | None]:
    d = getattr(event, "date", None)
    if not d:
        return (None, None)
    val = getattr(d, "value", None)
    if isinstance(val, date):
        return (val, val)
    start = getattr(val, "start", None)
    end = getattr(val, "end", None)
    return (start if isinstance(start, date) else None, end if isinstance(end, date) else None)


def _first_supported_fact(event: Event) -> str:
    pools = [
        getattr(event, "exam_findings", []) or [],
        getattr(event, "diagnoses", []) or [],
        getattr(event, "facts", []) or [],
        getattr(event, "procedures", []) or [],
    ]
    for pool in pools:
        for fact in pool:
            txt = _clean_line(getattr(fact, "text", ""))
            if not txt or _is_meta_language(txt):
                continue
            if getattr(fact, "technical_noise", False):
                continue
            return txt
    return "See cited record excerpt."


def _build_citation_maps(
    all_citations: list[Citation] | None,
    page_map: dict[int, tuple[str, int]] | None,
) -> tuple[dict[str, dict[str, Any]], dict[int, list[dict[str, Any]]], dict[str, set[int]], str | None]:
    by_id: dict[str, dict[str, Any]] = {}
    by_page: dict[int, list[dict[str, Any]]] = {}
    doc_pages: dict[str, set[int]] = {}
    single_doc_id: str | None = None
    if not all_citations:
        return by_id, by_page, doc_pages, single_doc_id
    doc_ids = set()
    for cit in all_citations:
        doc_id = str(cit.source_document_id)
        doc_ids.add(doc_id)
        filename = doc_id
        local_page = int(cit.page_number)
        if page_map and cit.page_number in page_map:
            mapped_name, mapped_page = page_map[cit.page_number]
            filename = mapped_name or filename
            local_page = int(mapped_page)
        row = {
            "citation_id": str(cit.citation_id),
            "doc_id": doc_id,
            "filename": filename,
            "global_page": int(cit.page_number),
            "local_page": local_page,
        }
        by_id[str(cit.citation_id)] = row
        by_page.setdefault(int(cit.page_number), []).append(row)
        doc_pages.setdefault(doc_id, set()).add(local_page)
    if len(doc_ids) == 1:
        single_doc_id = next(iter(doc_ids))
    return by_id, by_page, doc_pages, single_doc_id


def _event_citation_refs(
    event: Event,
    citation_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    ids = list(getattr(event, "citation_ids", []) or [])
    for fact in getattr(event, "facts", []) or []:
        if getattr(fact, "citation_id", None):
            ids.append(str(fact.citation_id))
        for cid in getattr(fact, "citation_ids", []) or []:
            ids.append(str(cid))
    for cid in ids:
        ref = citation_by_id.get(str(cid))
        if not ref:
            continue
        key = f"{ref['doc_id']}|{ref['local_page']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return sorted(out, key=lambda r: (r["filename"], r["local_page"]))[:6]


def _claim_row_citation_refs(
    row: dict[str, Any],
    by_page: dict[int, list[dict[str, Any]]],
    single_doc_id: str | None,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in (row.get("citations") or []):
        s = str(raw or "").strip()
        if not s:
            continue
        m = re.search(r"\bp\.\s*(\d+)\b", s, re.I)
        if not m:
            continue
        page_no = int(m.group(1))
        candidates = by_page.get(page_no, [])
        if candidates:
            ref = candidates[0]
        elif single_doc_id:
            ref = {"doc_id": single_doc_id, "filename": single_doc_id, "global_page": page_no, "local_page": page_no}
        else:
            ref = {"doc_id": "", "filename": "", "global_page": page_no, "local_page": page_no}
        key = f"{ref.get('doc_id','')}|{ref.get('local_page', page_no)}"
        if key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return refs[:6]


def _citation_links_and_text(
    refs: list[dict[str, Any]],
    *,
    row_anchor: str | None,
    manifest: RenderManifest | None,
) -> tuple[list[dict[str, str]], str]:
    links: list[dict[str, str]] = []
    labels: list[str] = []
    for ref in refs:
        page_no = int(ref.get("local_page") or ref.get("global_page") or 0)
        if page_no <= 0:
            continue
        label = f"p. {page_no}"
        labels.append(label)
        doc_id = str(ref.get("doc_id") or "")
        if doc_id:
            anchor = appendix_anchor(doc_id, page_no)
            links.append({"anchor": anchor, "label": label})
            if manifest and row_anchor:
                manifest.add_link(row_anchor, anchor)
    if not labels:
        return links, "Citation(s): Not available"
    return links, "Citation(s): " + " ".join(f"[{l}]" for l in labels)


def _paragraph_list_section(title: str, rows: list[Paragraph], title_style: Any) -> list:
    if not rows:
        return []
    return [Paragraph(title, title_style), Spacer(1, 0.06 * inch), *rows, Spacer(1, 0.08 * inch)]


def _safe_money(v: Any) -> str:
    try:
        if v is None or str(v).strip() == "":
            return "Not available"
        return f"${float(v):,.2f}"
    except Exception:
        return "Not available"


def _pt_intensity_summary(raw_events: list[Event] | None) -> dict[str, Any]:
    pt_events = [e for e in (raw_events or []) if str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))) == "pt_visit"]
    if not pt_events:
        return {}
    visit_candidates: list[int] = []
    start_dates: list[date] = []
    end_dates: list[date] = []
    citations: list[str] = []
    for e in pt_events:
        for fact in (getattr(e, "facts", []) or []):
            txt = str(getattr(fact, "text", "") or "")
            m = re.search(r"\bPT sessions documented:\s*(\d+)\b", txt, re.I)
            if m:
                visit_candidates.append(int(m.group(1)))
        s, e_date = _event_date_bounds(e)
        if s:
            start_dates.append(s)
        if e_date:
            end_dates.append(e_date)
    visits = max(visit_candidates) if visit_candidates else len(pt_events)
    return {
        "visits": visits,
        "start": min(start_dates).isoformat() if start_dates else None,
        "end": max(end_dates).isoformat() if end_dates else None,
        "event_count": len(pt_events),
    }


def _billing_is_complete(summary: dict | None) -> bool:
    if not isinstance(summary, dict):
        return False
    flags = {str(f) for f in (summary.get("flags") or [])}
    if flags & {"NO_BILLING_DATA", "PARTIAL_BILLING_ONLY", "MISSING_EOB_DATA"}:
        return False
    try:
        conf = float(summary.get("confidence") or 0)
    except Exception:
        conf = 0.0
    if conf < 0.85:
        return False
    totals = summary.get("totals") or {}
    return bool(totals.get("total_charges"))


def _renderer_manifest_payload(evidence_graph_payload: dict | None, renderer_manifest: dict | None = None) -> dict:
    if isinstance(renderer_manifest, dict) and renderer_manifest:
        return renderer_manifest
    ext = _ext_payload(evidence_graph_payload)
    rm = ext.get("renderer_manifest")
    return rm if isinstance(rm, dict) else {}


def _export_status_label(ext: dict, rm: dict) -> str:
    """
    Conservative export status label for attorney-facing PDF header.

    Render runs before final run-row status persistence in some paths, so default to
    REVIEW_RECOMMENDED unless we have strong evidence the export is clean.
    """
    lsv1 = ext.get("litigation_safe_v1") if isinstance(ext, dict) else None
    if isinstance(lsv1, dict):
        status = str(lsv1.get("status") or "").strip().upper()
        if status in {"VERIFIED", "REVIEW_RECOMMENDED", "BLOCKED"}:
            prq = ext.get("provider_resolution_quality") if isinstance(ext, dict) else None
            pt_gate = (((prq or {}).get("pt_ledger")) or {}).get("pt_provider_facility_gate") if isinstance(prq, dict) else None
            gate_status = str((pt_gate or {}).get("status") or "").strip().upper() if isinstance(pt_gate, dict) else ""
            if gate_status == "BLOCKED":
                return "BLOCKED"
            if gate_status == "REVIEW_RECOMMENDED" and status == "VERIFIED":
                status = "REVIEW_RECOMMENDED"
            # PT ledger variance is a deterministic review trigger even if other litigation checks pass.
            pt_recon = ext.get("pt_reconciliation") if isinstance(ext, dict) else None
            if isinstance(pt_recon, dict):
                verified = int(pt_recon.get("verified_pt_count") or 0)
                reported_max = pt_recon.get("reported_pt_count_max")
                try:
                    reported_max_i = int(reported_max) if reported_max is not None else None
                except Exception:
                    reported_max_i = None
                if verified == 0 and reported_max_i and reported_max_i > 0:
                    return "BLOCKED"
                if reported_max_i is not None and reported_max_i >= 10 and verified < 3 and status == "VERIFIED":
                    return "REVIEW_RECOMMENDED"
            return status
    qg = ext.get("quality_gate") if isinstance(ext, dict) else None
    if isinstance(qg, dict):
        if qg.get("overall_pass") is False:
            return "REVIEW_RECOMMENDED"
        if qg.get("overall_pass") is True:
            # Keep partial billing and explicit missing data in review mode for now.
            if str((rm or {}).get("billing_completeness") or "").lower() == "partial":
                return "REVIEW_RECOMMENDED"
            return "VERIFIED"
    return "REVIEW_RECOMMENDED"


def _litigation_safe_payload(ext: dict) -> dict[str, Any]:
    payload = ext.get("litigation_safe_v1") if isinstance(ext, dict) else None
    return payload if isinstance(payload, dict) else {}


def _litigation_gap_summary(lsv1: dict[str, Any]) -> tuple[bool, int]:
    computed = lsv1.get("computed") if isinstance(lsv1.get("computed"), dict) else {}
    try:
        max_gap_days = int(computed.get("max_gap_days") or 0)
    except Exception:
        max_gap_days = 0
    return (max_gap_days > 45, max_gap_days)


def _pt_evidence_payload(ext: dict) -> dict[str, Any]:
    pt_encounters = [r for r in (ext.get("pt_encounters") or []) if isinstance(r, dict)]
    pt_reported = [r for r in (ext.get("pt_count_reported") or []) if isinstance(r, dict)]
    pt_recon = ext.get("pt_reconciliation") if isinstance(ext.get("pt_reconciliation"), dict) else {}
    reported_vals = sorted({int(r.get("reported_count") or 0) for r in pt_reported if int(r.get("reported_count") or 0) > 0})
    return {
        "encounters": sorted(
            pt_encounters,
            key=lambda r: (
                str(r.get("encounter_date") or "9999-99-99"),
                int(r.get("page_number") or 0),
                str(r.get("provider_name") or ""),
            ),
        ),
        "reported": pt_reported,
        "verified_count": int(pt_recon.get("verified_pt_count") or len(pt_encounters) or 0),
        "reported_vals": reported_vals,
        "reported_min": (min(reported_vals) if reported_vals else None),
        "reported_max": (max(reported_vals) if reported_vals else None),
        "variance_flag": bool(pt_recon.get("variance_flag")),
        "severe_variance_flag": bool(pt_recon.get("severe_variance_flag")),
    }


def _pt_ledger_refs(row: dict[str, Any], citation_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return _refs_from_citation_ids([str(c) for c in (row.get("evidence_citation_ids") or [])], citation_by_id)


def _build_pt_reconciliation_table(pt_payload: dict[str, Any], styles: Any) -> list:
    verified = int(pt_payload.get("verified_count") or 0)
    reported_min = pt_payload.get("reported_min")
    reported_max = pt_payload.get("reported_max")
    if reported_min is None and reported_max is None:
        return []
    normal = styles["Normal"]
    small = ParagraphStyle("PtReconSmall", parent=normal, fontSize=8.5, leading=10.5)
    if reported_min == reported_max:
        reported_label = str(reported_max)
    else:
        reported_label = f"{reported_min}-{reported_max}"
    delta = None
    if reported_max is not None:
        try:
            delta = int(reported_max) - verified
        except Exception:
            delta = None
    rows = [
        [Paragraph("<b>PT Count Reconciliation</b>", small), Paragraph("", small)],
        [Paragraph("Verified (enumerated dated encounters)", small), Paragraph(f"{verified}", small)],
        [Paragraph("Reported in records (summary counts)", small), Paragraph(reported_label, small)],
        [Paragraph("Variance (reported max - verified)", small), Paragraph(str(delta) if delta is not None else "n/a", small)],
    ]
    tbl = Table(rows, colWidths=[3.9 * inch, 2.1 * inch])
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF1FB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    return [tbl]


def _build_pt_visit_ledger_section(
    pt_payload: dict[str, Any],
    *,
    styles: Any,
    manifest: RenderManifest | None,
    citation_by_id: dict[str, dict[str, Any]],
) -> list:
    encounters = list(pt_payload.get("encounters") or [])
    if not encounters:
        return []
    normal = styles["Normal"]
    small = ParagraphStyle("PtLedgerSmall", parent=normal, fontSize=8.5, leading=10)
    rows = [[
        Paragraph("<b>Date</b>", small),
        Paragraph("<b>Provider</b>", small),
        Paragraph("<b>Facility</b>", small),
        Paragraph("<b>Citation</b>", small),
    ]]
    def _display_identity(name_key: str, meta_key: str, unknown_label: str, label_prefix: str) -> str:
        name = _clean_line(row.get(name_key)) or unknown_label
        meta = row.get(meta_key) if isinstance(row.get(meta_key), dict) else {}
        conf = float(meta.get("confidence") or 0.0) if isinstance(meta, dict) else 0.0
        if name.lower() == unknown_label.lower():
            return unknown_label
        if conf < 0.60:
            return f"{label_prefix} (low confidence): {name}"
        return name
    for idx, row in enumerate(encounters):
        refs = _pt_ledger_refs(row, citation_by_id)
        row_anchor = chron_anchor(f"pt_ledger_{idx}")
        if manifest:
            manifest.add_chron_anchor(row_anchor)
        _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
        rows.append([
            Paragraph(f'<a name="{escape(row_anchor)}"/>{escape(str(row.get("encounter_date") or "Undated"))}', small),
            Paragraph(escape(_display_identity("provider_name", "provider_resolution", "Unknown Provider", "Provider")), small),
            Paragraph(escape(_display_identity("facility_name", "facility_resolution", "Unknown Facility", "Facility")), small),
            Paragraph(escape(cite_text), small),
        ])
    tbl = Table(rows, colWidths=[1.0 * inch, 2.0 * inch, 2.0 * inch, 1.5 * inch], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF1FB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [Paragraph("PT Visit Ledger", styles["Heading2"]), Paragraph("Enumerated dated PT encounters (primary evidence in this packet).", normal), Spacer(1, 0.04 * inch), tbl]


def _build_litigation_safety_check_flowables(lsv1: dict[str, Any], styles: Any) -> list:
    if not lsv1:
        return []
    h2 = ParagraphStyle("LitigationSafeH2", parent=styles["Heading2"], fontSize=10.5, textColor=colors.HexColor("#7C2D12"), spaceBefore=4, spaceAfter=3)
    normal = styles["Normal"]
    label = str(lsv1.get("status") or "REVIEW_RECOMMENDED").strip().upper() or "REVIEW_RECOMMENDED"
    if label == "BLOCKED":
        bg = "#FEF2F2"
        fg = "#991B1B"
        border = "#FCA5A5"
    elif label == "VERIFIED":
        bg = "#ECFDF5"
        fg = "#065F46"
        border = "#6EE7B7"
    else:
        bg = "#FFFBEB"
        fg = "#92400E"
        border = "#FCD34D"
    badge = ParagraphStyle(
        "LitigationSafeBadge",
        parent=normal,
        backColor=colors.HexColor(bg),
        borderColor=colors.HexColor(border),
        borderWidth=0.6,
        borderPadding=5,
        textColor=colors.HexColor(fg),
        spaceAfter=4,
    )
    bullet = ParagraphStyle("LitigationSafeBullet", parent=normal, leftIndent=12, bulletIndent=0, spaceAfter=2)
    rows: list = [Paragraph("Litigation Safety Check", h2), Paragraph(f"<b>Status:</b> {escape(label)}", badge)]
    failures = [f for f in (lsv1.get("failure_reasons") or []) if isinstance(f, dict)]
    if failures:
        rows.append(Paragraph("<b>Failure reasons</b>:", normal))
        for f in failures:
            code = str(f.get("code") or "").strip()
            msg = str(f.get("message") or "").strip()
            line = f"- {code}" + (f": {msg}" if msg else "")
            rows.append(Paragraph(escape(line), bullet))
    else:
        rows.append(Paragraph("No litigation-safe invariant failures detected.", normal))
    return rows


def _refs_from_citation_ids(citation_ids: list[str] | None, citation_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cid in citation_ids or []:
        ref = citation_by_id.get(str(cid))
        if not ref:
            continue
        key = f"{ref.get('doc_id')}|{ref.get('local_page')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out[:8]


def _manifest_promoted_by_category(rm: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in (rm.get("promoted_findings") or []):
        if not isinstance(item, dict):
            continue
        if not (item.get("citation_ids") or []):
            continue
        grouped.setdefault(str(item.get("category") or "unknown"), []).append(item)
    return grouped


def _manifest_semantic_family(item: dict[str, Any]) -> str:
    fam = str(item.get("semantic_family") or "").strip().lower()
    return fam


def _allow_page3_reinforcement_for_item(item: dict[str, Any]) -> bool:
    source_families = [str(x).strip().lower() for x in (item.get("source_families") or []) if str(x).strip()]
    source_count = int(item.get("finding_source_count") or 0)
    return source_count >= 2 and len(set(source_families)) >= 2


def _dedupe_key(text: str | None) -> str:
    s = _clean_line(text or "")
    s = re.sub(r"^[^\w]+", "", s, flags=re.UNICODE)
    s = re.sub(r"[\"'`]+", "", s)
    s = re.sub(r"[.:;,\s]+$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def _near_duplicate_seen(key: str, seen_keys: set[str]) -> bool:
    if key in seen_keys:
        return True
    # Generic containment-based dedupe helps avoid repeating the same finding with extra prefix/suffix text.
    for k in seen_keys:
        if len(key) >= 28 and key in k:
            return True
        if len(k) >= 28 and k in key:
            return True
        # Token overlap fallback for near-duplicate paraphrases.
        toks_a = {t for t in re.findall(r"[a-z0-9]+", key) if len(t) > 2}
        toks_b = {t for t in re.findall(r"[a-z0-9]+", k) if len(t) > 2}
        if len(toks_a) >= 4 and len(toks_b) >= 4:
            overlap = len(toks_a & toks_b)
            denom = min(len(toks_a), len(toks_b))
            if denom and (overlap / denom) >= 0.7:
                return True
    return False


def _is_generic_timeline_fact(text: str) -> bool:
    t = _dedupe_key(text)
    if not t:
        return True
    generic_patterns = [
        r"\bmri report reviewed; impression documented\b",
        r"\borthopedic consultation documented\b",
        r"\bfollow-?up and treatment planning noted\b",
        r"\bassessment: .*documented\b",
    ]
    return any(re.search(p, t, re.I) for p in generic_patterns)


def _is_pt_aggregate_count_label(text: str | None) -> bool:
    s = _clean_line(text or "")
    if not s:
        return False
    return bool(re.search(r"\b(?:Aggregated PT sessions|PT sessions documented)\b", s, re.I) and re.search(r"\b\d+\s+encounters?\b", s, re.I))


def _manifest_finding_paragraphs(
    rm: dict,
    *,
    categories: tuple[str, ...],
    styles: Any,
    manifest: RenderManifest | None,
    citation_by_id: dict[str, dict[str, Any]],
    by_page: dict[int, list[dict[str, Any]]] | None = None,
    single_doc_id: str | None = None,
    limit: int = 8,
    include_secondary: bool = False,
    headline_only: bool | None = None,
    exclude_semantic_families: set[str] | None = None,
) -> list[Paragraph]:
    normal = styles["Normal"]
    bullet = ParagraphStyle("ManifestFindingBullet", parent=normal, leftIndent=12, bulletIndent=0, spaceAfter=2)
    grouped = _manifest_promoted_by_category(rm)
    rows: list[Paragraph] = []
    secondary: list[Paragraph] = []
    seen: set[str] = set()
    for cat in categories:
        for item in grouped.get(cat, []):
            if headline_only is True and not item.get("headline_eligible", True):
                continue
            if headline_only is False and item.get("headline_eligible", True):
                continue
            fam = _manifest_semantic_family(item)
            if exclude_semantic_families and fam and fam in exclude_semantic_families and not _allow_page3_reinforcement_for_item(item):
                continue
            label = _guardrail_text(_clean_line(item.get("label")), supported_injury=True)
            if not label:
                continue
            if _is_pt_aggregate_count_label(label):
                continue
            key = label.lower()
            if key in seen:
                continue
            raw_cits = [str(c) for c in (item.get("citation_ids") or [])]
            refs = _refs_from_citation_ids(raw_cits, citation_by_id)
            if not refs and raw_cits and by_page is not None:
                refs = _claim_row_citation_refs({"citations": raw_cits}, by_page, single_doc_id)
            if not refs:
                continue
            seen.add(key)
            row_anchor = chron_anchor(str(item.get("source_event_id") or f"mf_{cat}_{len(rows)+len(secondary)}"))
            if manifest:
                manifest.add_chron_anchor(row_anchor)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
            para = Paragraph(
                f'<a name="{escape(row_anchor)}"/>- {escape(label)}<br/><font size="8">{escape(cite_text)}</font>',
                bullet,
            )
            if not item.get("headline_eligible", True) or str(item.get("severity") or "").lower() == "low":
                secondary.append(para)
            else:
                rows.append(para)
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    if include_secondary and secondary and len(rows) < limit:
        rows.extend(secondary[: max(0, limit - len(rows))])
    return rows


def _build_timeline_table(
    projection: ChronologyProjection,
    styles: Any,
    manifest: RenderManifest | None,
    citation_refs_by_event: dict[str, list[dict[str, Any]]],
    by_page: dict[int, list[dict[str, Any]]] | None = None,
    single_doc_id: str | None = None,
) -> list:
    normal = styles["Normal"]
    small = ParagraphStyle("TimelineSmall", parent=normal, fontSize=8.5, leading=10.5)
    cell = ParagraphStyle("TimelineCell", parent=normal, fontSize=9, leading=11)
    header = [
        Paragraph("<b>Date</b>", cell),
        Paragraph("<b>Provider</b>", cell),
        Paragraph("<b>Event Type</b>", cell),
        Paragraph("<b>Key Finding</b>", cell),
        Paragraph("<b>Citations</b>", cell),
    ]
    rows = [header]
    seen = set()
    pt_rows = 0
    scored = sorted(
        list(projection.entries),
        key=lambda e: (
            parse_date_string(getattr(e, "date_display", "") or "") or date.max,
            -len(getattr(e, "citation_display", "") or ""),
            str(getattr(e, "event_id", "")),
        ),
    )
    def _timeline_provider_display(entry: Any, key_finding: str) -> str:
        provider = _clean_line(getattr(entry, "provider_display", "") or "")
        etype = _clean_line(getattr(entry, "event_type_display", "") or "").lower()
        finding_low = (key_finding or "").lower()
        provider_low = provider.lower()
        if "general hospital" in finding_low:
            return "General Hospital & Trauma Center"
        if provider_low in {"unknown", "provider not stated"}:
            return "Provider not clearly identified"
        # Do not present PT provider names as if they authored imaging/ER/procedure records.
        if re.search(r"\b(physical therapy|\\bpt\\b)\b", provider_low):
            if any(x in etype for x in ("imaging", "emergency", "procedure")):
                return "Provider not clearly identified"
            if "clinical note" in etype and "physical therapy" not in finding_low and "pt " not in f" {finding_low} ":
                return "Provider not clearly identified"
        if provider and provider == provider.lower() and re.fullmatch(r"[a-z0-9&'./ -]+", provider):
            provider = " ".join(w.capitalize() if w not in {"of", "and", "the"} else w for w in provider.split())
        return provider or "Provider not clearly identified"

    for entry in scored:
        if not getattr(entry, "citation_display", ""):
            continue
        etype_low = str(entry.event_type_display or "").lower()
        if "billing" in etype_low:
            continue
        facts = [f for f in (getattr(entry, "facts", []) or []) if _clean_line(f)]
        candidates = [f for f in facts if not _is_meta_language(f)]
        key_finding = _clean_line(next((f for f in candidates if not _is_generic_timeline_fact(f)), candidates[0] if candidates else ""))
        if not key_finding:
            continue
        if re.search(r"\bAggregated PT sessions\b", key_finding, re.I):
            # Aggregated PT counts are secondary evidence and should not appear as unlabeled timeline facts.
            continue
        if _is_generic_timeline_fact(key_finding):
            continue
        row_key = (entry.date_display, entry.provider_display, entry.event_type_display, key_finding[:120])
        if row_key in seen:
            continue
        seen.add(row_key)
        if ("therapy" in etype_low or "pt" in etype_low) and pt_rows >= 6:
            continue
        if "therapy" in etype_low or "pt" in etype_low:
            pt_rows += 1

        row_anchor = chron_anchor(str(entry.event_id))
        if manifest:
            manifest.add_chron_anchor(row_anchor)
        refs = citation_refs_by_event.get(str(entry.event_id), [])
        if not refs and getattr(entry, "citation_display", "") and by_page is not None:
            refs = _claim_row_citation_refs({"citations": [c.strip() for c in str(entry.citation_display).split(",")]}, by_page, single_doc_id)
        if not refs:
            continue
        _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
        if "Not available" in cite_text:
            continue
        provider_display = _timeline_provider_display(entry, key_finding)
        date_cell = _attorney_date_display(getattr(entry, "date_display", ""))
        rows.append([
            Paragraph(f'<a name="{escape(row_anchor)}"/>{escape(date_cell)}', small),
            Paragraph(escape(provider_display), small),
            Paragraph(escape(_clean_line(entry.event_type_display) or "Event"), small),
            Paragraph(escape(key_finding), small),
            Paragraph(escape(cite_text), small),
        ])
        if len(rows) >= 38:
            break

    if len(rows) == 1:
        return [Paragraph("No citation-anchored timeline rows were available for export.", normal)]

    tbl = Table(rows, colWidths=[1.0 * inch, 1.4 * inch, 1.0 * inch, 2.9 * inch, 1.2 * inch], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF1FB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [tbl]


def _build_claim_row_sections(
    ext: dict,
    styles: Any,
    manifest: RenderManifest | None,
    by_page: dict[int, list[dict[str, Any]]],
    single_doc_id: str | None,
    *,
    section_kind: str,
) -> list:
    normal = styles["Normal"]
    bullet = ParagraphStyle(f"{section_kind}Bullet", parent=normal, leftIndent=12, bulletIndent=0, spaceAfter=2)
    rows: list[dict[str, Any]] = list(ext.get("claim_rows") or [])
    selected: list[tuple[str, list[dict[str, Any]]]] = []
    seen = set()

    def include_row(r: dict[str, Any]) -> bool:
        ctype = str(r.get("claim_type") or "")
        assertion = _clean_line(r.get("assertion"))
        if not assertion or _is_undermining_or_noise(assertion):
            return False
        if not (r.get("citations") or []):
            return False
        low = assertion.lower()
        if section_kind == "imaging":
            if ctype != "IMAGING_FINDING":
                return False
            if "compare." in low or "vitals check" in low:
                return False
            return True
        if section_kind == "objective":
            return any(k in low for k in ["4/5", "strength", "weakness", "spasm", "lordosis", "rom", "reflex"])
        if section_kind == "dx":
            if ctype != "INJURY_DX":
                return False
            return True
        return False

    ordered = sorted(rows, key=lambda r: (str(r.get("date") or "9999-99-99"), -(int(r.get("selection_score") or 0))))
    for r in ordered:
        if not include_row(r):
            continue
        assertion = _clean_line(r.get("assertion"))
        low = assertion.lower()
        if _is_pt_aggregate_count_label(assertion):
            return False
        if section_kind == "imaging" and re.search(r"\b(no acute|unremarkable|no significant degenerative)\b", low):
            pri = "secondary"
        else:
            pri = "primary"
        key = assertion.lower()
        if key in seen:
            continue
        seen.add(key)
        refs = _claim_row_citation_refs(r, by_page, single_doc_id)
        if not refs:
            continue
        selected.append((pri, refs))
        if len(selected) >= 10:
            break

    primary_rows: list[Paragraph] = []
    secondary_rows: list[Paragraph] = []
    used_assertions = set()
    for r in ordered:
        if not include_row(r):
            continue
        assertion = _clean_line(r.get("assertion"))
        if assertion.lower() in used_assertions:
            continue
        used_assertions.add(assertion.lower())
        refs = _claim_row_citation_refs(r, by_page, single_doc_id)
        if not refs:
            continue
        row_anchor = chron_anchor(str(r.get("event_id") or f"{section_kind}_{len(used_assertions)}"))
        if manifest:
            manifest.add_chron_anchor(row_anchor)
        _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
        para = Paragraph(
            f'<a name="{escape(row_anchor)}"/>- {escape(assertion)}<br/><font size="8">{escape(cite_text)}</font>',
            bullet,
        )
        if section_kind == "imaging" and re.search(r"\b(no acute|unremarkable|no significant degenerative)\b", assertion.lower()):
            secondary_rows.append(para)
        else:
            primary_rows.append(para)
        if len(primary_rows) >= 8:
            break
    out: list = []
    out.extend(primary_rows)
    if secondary_rows:
        out.append(Paragraph("<i>Secondary / non-headline imaging observations:</i>", normal))
        out.extend(secondary_rows[:3])
    return out


def build_billing_specials_section(
    specials_summary: dict | None,
    styles: Any,
    *,
    manifest: RenderManifest | None = None,
    citation_by_id: dict[str, dict[str, Any]] | None = None,
    billing_completeness: str | None = None,
) -> list:
    """Page 5 billing/specials summary with incomplete-data safeguards."""
    title_style = styles["Heading1"]
    normal = styles["Normal"]
    small = ParagraphStyle("BillingSmall", parent=normal, fontSize=9, leading=11)
    flowables: list = [Paragraph("Billing / Specials", title_style), Spacer(1, 0.08 * inch)]

    if not isinstance(specials_summary, dict):
        flowables.append(Paragraph("Billing extraction status: Not available in packet extraction.", normal))
        return flowables

    status = str(billing_completeness or ("complete" if _billing_is_complete(specials_summary) else "partial"))
    complete = status == "complete"
    flags = [str(f) for f in (specials_summary.get("flags") or [])]
    coverage = specials_summary.get("coverage") or {}
    dedupe = specials_summary.get("dedupe") or {}
    totals = specials_summary.get("totals") or {}

    if complete:
        flowables.append(Paragraph("Billing extraction status: Complete (record-supported totals available).", normal))
    elif status == "none":
        flowables.append(Paragraph("<b>Billing extraction status: No billing data extracted from packet.</b>", normal))
    else:
        flowables.append(Paragraph("<b>Billing extraction incomplete.</b>", normal))
        warn = ParagraphStyle(
            "BillingPartialWarn",
            parent=normal,
            backColor=colors.HexColor("#FEF2F2"),
            borderColor=colors.HexColor("#FCA5A5"),
            borderWidth=0.6,
            borderPadding=5,
            textColor=colors.HexColor("#7F1D1D"),
            spaceAfter=4,
        )
        flowables.append(Paragraph("<b>Partial Billing Extract Only - Not Total Specials.</b>", warn))
        flowables.append(Paragraph("Total billed is not shown as a case total because extracted billing appears partial or lacks complete EOB/adjustment coverage.", small))

    meta_bits = []
    if coverage.get("billing_pages_count") is not None:
        meta_bits.append(f"Billing pages detected: {coverage.get('billing_pages_count')}")
    if coverage.get("earliest_service_date") or coverage.get("latest_service_date"):
        meta_bits.append(
            f"Coverage window: {coverage.get('earliest_service_date') or 'unknown'} to {coverage.get('latest_service_date') or 'unknown'}"
        )
    if dedupe.get("lines_deduped") is not None:
        meta_bits.append(
            f"Billing lines: {dedupe.get('lines_deduped')} deduped"
            + (f" ({dedupe.get('lines_raw')} raw)" if dedupe.get("lines_raw") is not None else "")
        )
    if meta_bits:
        flowables.append(Paragraph(" | ".join(meta_bits), small))
    if flags:
        flowables.append(Paragraph(f"Flags: {', '.join(flags)}", small))
    flowables.append(Spacer(1, 0.08 * inch))

    if complete:
        data = [
            ["Total billed", _safe_money(totals.get("total_charges"))],
            ["Total paid", _safe_money(totals.get("total_payments"))],
            ["Total adjustments", _safe_money(totals.get("total_adjustments"))],
            ["Total balance", _safe_money(totals.get("total_balance"))],
        ]
    else:
        data = [["Partial Extracted Charges", "Not available from extracted records (incomplete billing extraction)"]]
    totals_tbl = Table(data, colWidths=[2.0 * inch, 4.8 * inch])
    totals_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
    ]))
    flowables.append(totals_tbl)
    flowables.append(Spacer(1, 0.12 * inch))

    by_provider = list(specials_summary.get("by_provider") or [])
    if by_provider:
        rows = [[
            Paragraph("<b>Provider</b>", small),
            Paragraph("<b>Line Items</b>", small),
            Paragraph(f"<b>{'Partial Extracted Charges' if status == 'partial' else 'Charges'}</b>", small),
            Paragraph("<b>Citations</b>", small),
        ]]
        dropped_uncited_provider_rows = 0
        for item in sorted(by_provider, key=lambda x: float(x.get("charges") or 0), reverse=True)[:10]:
            refs: list[dict[str, Any]] = []
            for cid in (item.get("citation_ids_sample") or [])[:4]:
                ref = (citation_by_id or {}).get(str(cid))
                if ref:
                    refs.append(ref)
            if not refs:
                dropped_uncited_provider_rows += 1
                continue
            row_anchor = chron_anchor(f"billing_{re.sub(r'[^a-zA-Z0-9]+', '_', str(item.get('provider_display_name') or 'provider'))[:24]}")
            if manifest:
                manifest.add_chron_anchor(row_anchor)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
            provider_label = str(item.get("provider_display_name") or "Unknown provider")
            if provider_label.strip().lower() == "unresolved provider":
                provider_label = "Provider name unresolved (partial billing extraction)"
            rows.append([
                Paragraph(f'<a name="{escape(row_anchor)}"/>{escape(provider_label)}', small),
                Paragraph(str(item.get("line_count") or 0), small),
                Paragraph((_safe_money(item.get("charges")) + (" <font color='#64748B'>(partial extracted charges)</font>" if status == "partial" else "")), small),
                Paragraph(escape(cite_text), small),
            ])
        if len(rows) > 1:
            tbl = Table(rows, colWidths=[2.9 * inch, 0.9 * inch, 1.1 * inch, 1.9 * inch], repeatRows=1)
            tbl.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF1FB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            flowables.append(Paragraph("Known extracted billing line groups (record-supported):", normal))
            flowables.append(Spacer(1, 0.05 * inch))
            flowables.append(tbl)
            if status == "partial":
                flowables.append(Spacer(1, 0.05 * inch))
                flowables.append(Paragraph("Provider charge amounts above are partial extracted subtotals and should not be treated as complete specials totals or completeness ratios.", small))
        else:
            flowables.append(Paragraph("Known line items: Not available in packet extraction.", normal))
        if dropped_uncited_provider_rows:
            logger.info("billing provider rows dropped due to missing citations: %s", dropped_uncited_provider_rows)
    else:
        flowables.append(Paragraph("Known line items: Not available in packet extraction.", normal))

    return flowables


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
    specials_summary: dict | None = None,
    renderer_manifest: dict | None = None,
    run_id: str | None = None,
) -> bytes:
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=18, spaceAfter=10)
    h1_style = ParagraphStyle("H1Style", parent=styles["Heading1"], fontSize=14, spaceBefore=8, spaceAfter=5, textColor=colors.HexColor("#2E548A"))
    h2_style = ParagraphStyle("H2StyleLit", parent=styles["Heading2"], fontSize=11, spaceBefore=6, spaceAfter=4, textColor=colors.HexColor("#1F3B63"))
    normal_style = styles["Normal"]
    normal_style.leading = 12

    manifest = RenderManifest()
    ext = _ext_payload(evidence_graph_payload)
    lsv1 = _litigation_safe_payload(ext)
    pt_payload = _pt_evidence_payload(ext)
    rm = _renderer_manifest_payload(evidence_graph_payload, renderer_manifest)
    citation_by_id, citations_by_page, _doc_pages, single_doc_id = _build_citation_maps(all_citations, page_map)
    raw_events = raw_events or []
    projection_by_event = {str(e.event_id): e for e in projection.entries}
    event_citations_by_event = {str(e.event_id): _event_citation_refs(e, citation_by_id) for e in raw_events}
    supported_injury = _has_supported_disc_injury(ext, raw_events)
    moat_stats: dict = {}

    def _event_or_entry_provider(evt: Event) -> str:
        entry = projection_by_event.get(str(evt.event_id))
        if entry and getattr(entry, "provider_display", None):
            return _clean_line(entry.provider_display)
        return "Provider not stated"

    def _event_or_entry_citation_text(evt: Event, row_anchor: str) -> str:
        refs = event_citations_by_event.get(str(evt.event_id), [])
        _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
        return cite_text

    # Page 1 - Case Snapshot
    flowables = [Paragraph(f"Medical Chronology: {matter_title}", title_style)]
    flowables.append(Paragraph("CASE SNAPSHOT (30-SECOND READ)", h1_style))

    patient_label = next((str(getattr(e, "patient_label", "")).strip() for e in projection.entries if str(getattr(e, "patient_label", "")).strip() and "unknown" not in str(getattr(e, "patient_label", "")).lower()), "Patient name not reliably extracted from packet")
    if patient_label.strip().lower() == "see patient header":
        patient_label = "Patient name not reliably extracted from packet"
    dated_events = [e for e in raw_events if _event_date_bounds(e)[0]]
    dated_events.sort(key=lambda e: _event_date_bounds(e)[0] or date.max)
    doi = (_event_date_bounds(dated_events[0])[0].isoformat() if dated_events else None)
    mechanism = None
    for evt in raw_events:
        blob = " ".join([str(getattr(f, "text", "") or "") for f in (getattr(evt, "facts", []) or [])]).lower()
        if "rear-end" in blob or "rear end" in blob:
            mechanism = "rear-end motor vehicle collision"
            break
        if "mva" in blob or "mvc" in blob or "motor vehicle" in blob or "collision" in blob:
            mechanism = "motor vehicle collision"
            break
        if "fall" in blob:
            mechanism = "fall"
    rm_doi = ((rm.get("doi") or {}).get("value") if isinstance(rm, dict) else None)
    rm_doi_source = ((rm.get("doi") or {}).get("source") if isinstance(rm, dict) else None)
    if rm_doi and not is_sentinel_date(rm_doi) and str(rm_doi_source or "").lower() != "not_found":
        doi_display = str(rm_doi)
    else:
        doi_display = doi if doi and not is_sentinel_date(doi) else "Not clearly extracted from packet"
    rm_mechanism = ((rm.get("mechanism") or {}).get("value") if isinstance(rm, dict) else None)
    mechanism_display = str(rm_mechanism) if rm_mechanism else (mechanism or "Not clearly extracted from packet")
    export_status = _export_status_label(ext, rm)

    header_rows = [
        ["Case", matter_title],
        ["Patient", patient_label],
        ["DOI", doi_display],
        ["Mechanism", mechanism_display],
        ["Export Status", export_status],
    ]
    header_tbl = Table(header_rows, colWidths=[1.1 * inch, 5.7 * inch])
    header_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flowables.append(header_tbl)
    flowables.append(Spacer(1, 0.12 * inch))
    flowables.append(Paragraph(f"Export Status = {export_status}", ParagraphStyle("ExportStatusLine", parent=normal_style, fontSize=8.5, textColor=colors.HexColor('#334155'), spaceAfter=4)))
    flowables.extend(_build_litigation_safety_check_flowables(lsv1, styles))
    if lsv1:
        flowables.append(Spacer(1, 0.05 * inch))

    flowables.append(Paragraph("Case Highlights (Record-Supported)", h2_style))
    flowables.append(Paragraph("Record-supported highlights selected from citation-anchored findings; not a legal conclusion.", ParagraphStyle("SnapshotMeta", parent=normal_style, fontSize=8.5, textColor=colors.HexColor("#475569"), spaceAfter=4)))
    settlement_driver_rows: list[Paragraph] = []
    snapshot_promoted_semantic_families: set[str] = set()
    bullet_style = ParagraphStyle("SnapshotBullet", parent=normal_style, leftIndent=12, bulletIndent=0, spaceAfter=2)

    # Early care / ER on DOI
    first_er = next((e for e in dated_events if str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))) in {"er_visit", "hospital_admission", "hospital_discharge", "inpatient_daily_note"}), None)
    if first_er:
        a = chron_anchor(str(first_er.event_id))
        manifest.add_chron_anchor(a)
        cite_text = _event_or_entry_citation_text(first_er, a)
        settlement_driver_rows.append(Paragraph(
            f'<a name="{escape(a)}"/>- Early care documented: {escape(_event_date_label(first_er))} acute/initial treatment encounter. <font size="8">{escape(cite_text)}</font>',
            bullet_style
        ))

    rm_mech = rm.get("mechanism") if isinstance(rm, dict) else {}
    if isinstance(rm_mech, dict) and _clean_line(rm_mech.get("value")) and (rm_mech.get("citation_ids") or []):
        refs = _refs_from_citation_ids([str(c) for c in (rm_mech.get("citation_ids") or [])], citation_by_id)
        if refs:
            a = chron_anchor("mechanism")
            manifest.add_chron_anchor(a)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
            settlement_driver_rows.append(Paragraph(
                f'<a name="{escape(a)}"/>- Mechanism documented: {escape(_clean_line(rm_mech.get("value")))}. <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            ))

    # Continuous care if no global gap >45
    mr_payload = missing_records_payload or ext.get("missing_records") or {}
    global_gaps = [g for g in (mr_payload.get("gaps") or []) if str(g.get("rule_name") or "") == "global_gap" and int(g.get("gap_days") or 0) > 45]
    raw_gaps_gt45 = [g for g in (gaps or []) if int(getattr(g, "duration_days", 0) or 0) > 45]
    lsv1_gap_gt45, lsv1_max_gap_days = _litigation_gap_summary(lsv1)
    if not lsv1_gap_gt45 and not global_gaps and not raw_gaps_gt45:
        # cite first and last dated events if available
        if dated_events:
            start_evt = dated_events[0]
            end_evt = dated_events[-1]
            a = chron_anchor(f"continuity_{start_evt.event_id}")
            manifest.add_chron_anchor(a)
            refs = (event_citations_by_event.get(str(start_evt.event_id), []) + event_citations_by_event.get(str(end_evt.event_id), []))[:6]
            _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
            settlement_driver_rows.append(Paragraph(
                f'<a name="{escape(a)}"/>- Continuous care signal: no computed global treatment gaps >45 days in extracted encounter chronology. <font size="8">{escape(cite_text)}</font>',
                bullet_style
            ))

    # Promoted findings from renderer manifest (pipeline-ranked, citation-backed)
    promoted_by_cat = _manifest_promoted_by_category(rm)
    promoted_page1_considered = 0
    promoted_page1_rendered = 0
    settlement_seen_labels: set[str] = set()
    strong_objective_snapshot = any(
        re.search(r"\b(weakness|diminished|reflex|[0-5]/5)\b", str(item.get("label") or ""), re.I)
        and bool(item.get("headline_eligible", True))
        for item in promoted_by_cat.get("objective_deficit", [])
    )
    snapshot_promoted_order = (
        ("objective_deficit", "imaging", "diagnosis", "procedure")
        if strong_objective_snapshot
        else ("imaging", "diagnosis", "objective_deficit", "procedure")
    )
    for cat in snapshot_promoted_order:
        for item in promoted_by_cat.get(cat, []):
            promoted_page1_considered += 1
            if not item.get("headline_eligible", True):
                logger.info("page1 promoted finding omitted: reason=filtered category=%s label=%s", cat, _clean_line(item.get("label")))
                continue
            raw_cits = [str(c) for c in (item.get("citation_ids") or [])]
            refs = _refs_from_citation_ids(raw_cits, citation_by_id)
            if not refs and raw_cits:
                refs = _claim_row_citation_refs({"citations": raw_cits}, citations_by_page, single_doc_id)
            if not refs:
                logger.info("page1 promoted finding omitted: reason=uncited category=%s label=%s", cat, _clean_line(item.get("label")))
                continue
            row_anchor = chron_anchor(str(item.get("source_event_id") or f"pf_{cat}_{len(settlement_driver_rows)}"))
            manifest.add_chron_anchor(row_anchor)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
            label = _guardrail_text(_clean_line(item.get("label")), supported_injury=supported_injury)
            if not label:
                logger.info("page1 promoted finding omitted: reason=guardrail category=%s", cat)
                continue
            if _is_pt_aggregate_count_label(label):
                logger.info("page1 promoted finding omitted: reason=pt_aggregate_count category=%s", cat)
                continue
            label_dedupe = _dedupe_key(label)
            if _near_duplicate_seen(label_dedupe, settlement_seen_labels):
                logger.info("page1 promoted finding omitted: reason=duplicate category=%s label=%s", cat, label)
                continue
            pretty_cat = cat.replace("_", " ").title()
            settlement_driver_rows.append(Paragraph(
                f'<a name="{escape(row_anchor)}"/>- {escape(pretty_cat + ": " + label)} <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            ))
            settlement_seen_labels.add(label_dedupe)
            fam = _manifest_semantic_family(item)
            if fam:
                snapshot_promoted_semantic_families.add(fam)
            promoted_page1_rendered += 1
            break
    if promoted_page1_considered and promoted_page1_rendered == 0:
        logger.warning("page1 promoted findings parity issue: considered=%s rendered=%s", promoted_page1_considered, promoted_page1_rendered)

    # Objective findings / diagnoses / imaging from claim rows
    claim_rows = list(ext.get("claim_rows") or [])
    def _pick_claim(patterns: list[str], claim_types: set[str] | None = None, exclude_negative: bool = False) -> dict | None:
        for row in sorted(claim_rows, key=lambda r: (str(r.get("date") or "9999-99-99"), -(int(r.get("selection_score") or 0)))):
            assertion = _clean_line(row.get("assertion"))
            low = assertion.lower()
            if claim_types and str(row.get("claim_type") or "") not in claim_types:
                continue
            if exclude_negative and re.search(r"\b(no acute|unremarkable|no significant degenerative)\b", low):
                continue
            if any(re.search(p, low, re.I) for p in patterns) and (row.get("citations") or []):
                return row
        return None

    for label, patterns, claim_types in [
        ("Objective findings", [r"4/5", r"weakness", r"spasm", r"lordosis"], None),
        ("Imaging findings", [r"disc", r"foramen", r"foraminal", r"c5-?c6", r"radiculopathy", r"herniat", r"protrusion"], {"IMAGING_FINDING"}),
        ("Diagnoses", [r"disc", r"radiculopathy", r"displacement", r"strain", r"sprain"], {"INJURY_DX"}),
    ]:
        row = _pick_claim(patterns, claim_types, exclude_negative=True)
        if not row:
            continue
        refs = _claim_row_citation_refs(row, citations_by_page, single_doc_id)
        if not refs:
            continue
        a = chron_anchor(str(row.get("event_id") or f"claim_{label.lower()}"))
        manifest.add_chron_anchor(a)
        _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
        txt = _guardrail_text(f"- {label}: {_clean_line(row.get('assertion'))}.", supported_injury=supported_injury)
        if txt:
            settlement_driver_rows.append(Paragraph(f'<a name="{escape(a)}"/>{escape(txt)} <font size="8">{escape(cite_text)}</font>', bullet_style))

    rm_pt = rm.get("pt_summary") if isinstance(rm, dict) else {}
    pt_summary = _pt_intensity_summary(raw_events)
    if pt_payload.get("verified_count") is not None and (pt_payload.get("verified_count") or pt_payload.get("reported_vals")):
        pt_summary = {
            "visits": int(pt_payload.get("verified_count") or 0),
            "start": (pt_payload.get("encounters")[0].get("encounter_date") if pt_payload.get("encounters") else None),
            "end": (pt_payload.get("encounters")[-1].get("encounter_date") if pt_payload.get("encounters") else None),
            "count_source": "event_count",
        }
    elif isinstance(rm_pt, dict) and rm_pt.get("total_encounters") is not None:
        pt_summary = {
            "visits": int(rm_pt.get("total_encounters") or 0),
            "start": None if is_sentinel_date(rm_pt.get("date_start")) else rm_pt.get("date_start"),
            "end": None if is_sentinel_date(rm_pt.get("date_end")) else rm_pt.get("date_end"),
            "count_source": rm_pt.get("count_source"),
        }
    if pt_summary.get("visits") is not None:
        pt_evt = next((e for e in raw_events if str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))) == "pt_visit"), None)
        row_anchor = chron_anchor("pt_intensity")
        manifest.add_chron_anchor(row_anchor)
        refs = _refs_from_citation_ids([str(c) for c in (rm_pt.get("citation_ids") or [])], citation_by_id) if isinstance(rm_pt, dict) else []
        if not refs:
            refs = event_citations_by_event.get(str(pt_evt.event_id), []) if pt_evt else []
        _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
        duration_txt = ""
        if pt_summary.get("start") and pt_summary.get("end"):
            duration_txt = f"; care duration {pt_summary['start']} to {pt_summary['end']}"
        settlement_driver_rows.append(Paragraph(
            f'<a name="{escape(row_anchor)}"/>- Treatment intensity: PT visits (Verified) {pt_summary["visits"]} encounters{duration_txt}. <font size="8">{escape(cite_text)}</font>',
            bullet_style,
        ))
        if pt_payload.get("reported_max") is not None:
            rep_min = pt_payload.get("reported_min")
            rep_max = pt_payload.get("reported_max")
            rep_label = str(rep_max) if rep_min == rep_max else f"{rep_min}-{rep_max}"
            settlement_driver_rows.append(Paragraph(
                f"- PT visits (Reported in records): {escape(rep_label)} encounters.",
                bullet_style,
            ))
        if isinstance(rm_pt, dict) and _clean_line(rm_pt.get("reconciliation_note")):
            settlement_driver_rows.append(Paragraph(
                f"- PT count reconciliation: {escape(_clean_line(rm_pt.get('reconciliation_note')))}",
                bullet_style,
            ))

    snapshot_warnings: list[str] = []
    if mechanism_display == "Not clearly extracted from packet":
        snapshot_warnings.append("Mechanism not clearly extracted into summary; review timeline and appendix for causation anchors.")
    has_img = bool(promoted_by_cat.get("imaging"))
    has_dx = bool(promoted_by_cat.get("diagnosis"))
    if not has_img:
        snapshot_warnings.append("Imaging findings were not promoted into the snapshot summary.")
    if not has_dx:
        snapshot_warnings.append("Diagnoses were not promoted into the snapshot summary.")
    if isinstance(rm, dict) and str(rm.get("billing_completeness") or "") == "partial":
        snapshot_warnings.append("Billing extraction is partial; specials totals are not complete.")
    if snapshot_warnings:
        warn_style = ParagraphStyle("SnapshotWarn", parent=normal_style, backColor=colors.HexColor("#FFF7ED"), borderColor=colors.HexColor("#FDBA74"), borderWidth=0.5, borderPadding=4, spaceAfter=6)
        flowables.append(Paragraph("<b>Snapshot completeness notes</b>: " + " ".join(snapshot_warnings), warn_style))

    if not settlement_driver_rows:
        settlement_driver_rows.append(Paragraph("- No fully citation-supported settlement drivers were available for front-page display.", bullet_style))
    flowables.extend(settlement_driver_rows[:8])
    flowables.append(Spacer(1, 0.1 * inch))

    flowables.append(Paragraph("Top Record Anchors", h2_style))
    top_anchor_rows: list[Paragraph] = []
    top_seen = set()
    top_anchor_seen_families: set[str] = set()
    visit_count_max: int | None = None
    for item in promoted_by_cat.get("visit_count", []):
        m = re.search(r"\b(\d+)\s+encounters?\b", str(item.get("label") or ""), re.I)
        if m:
            n = int(m.group(1))
            visit_count_max = n if visit_count_max is None else max(visit_count_max, n)
    # Prefer manifest-promoted findings first (pipeline-ranked, citation-backed), then event/claim fallbacks.
    strong_objective_headline = any(
        re.search(r"\b(weakness|diminished|reflex|[0-5]/5)\b", str(item.get("label") or ""), re.I)
        and bool(item.get("headline_eligible", True))
        for item in promoted_by_cat.get("objective_deficit", [])
    )
    anchor_cat_order = (
        ("objective_deficit", "imaging", "diagnosis", "procedure", "visit_count", "symptom")
        if strong_objective_headline
        else ("imaging", "diagnosis", "objective_deficit", "procedure", "visit_count", "symptom")
    )
    for cat in anchor_cat_order:
        for item in promoted_by_cat.get(cat, []):
            if len(top_anchor_rows) >= 6:
                break
            if not item.get("headline_eligible", True) and cat in {"objective_deficit", "diagnosis", "imaging", "procedure"}:
                continue
            if cat == "visit_count" and visit_count_max is not None:
                m = re.search(r"\b(\d+)\s+encounters?\b", str(item.get("label") or ""), re.I)
                if m and int(m.group(1)) < visit_count_max:
                    continue
            assertion = _guardrail_text(_clean_line(item.get("label")), supported_injury=supported_injury)
            dedupe = _dedupe_key(assertion)
            if not assertion or _is_pt_aggregate_count_label(assertion) or _near_duplicate_seen(dedupe, top_seen) or _is_undermining_or_noise(assertion):
                continue
            raw_cits = [str(c) for c in (item.get("citation_ids") or [])]
            refs = _refs_from_citation_ids(raw_cits, citation_by_id)
            if not refs and raw_cits:
                refs = _claim_row_citation_refs({"citations": raw_cits}, citations_by_page, single_doc_id)
            if not refs:
                continue
            fam = _manifest_semantic_family(item)
            if fam and fam in top_anchor_seen_families and not _allow_page3_reinforcement_for_item(item):
                continue
            top_seen.add(dedupe)
            a = chron_anchor(str(item.get("source_event_id") or f"top_pf_{len(top_anchor_rows)}"))
            manifest.add_chron_anchor(a)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
            top_anchor_rows.append(Paragraph(
                f'<a name="{escape(a)}"/>- {escape(assertion)} <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            ))
            if fam:
                top_anchor_seen_families.add(fam)
    manifest_driver_ids = [str(x) for x in (rm.get("top_case_drivers") or [])] if isinstance(rm, dict) else []
    if manifest_driver_ids and len(top_anchor_rows) < 6:
        projection_entries_by_id = {str(e.event_id): e for e in projection.entries}
        for eid in manifest_driver_ids:
            if len(top_anchor_rows) >= 6:
                break
            refs = event_citations_by_event.get(eid, [])
            entry = projection_entries_by_id.get(eid)
            if not refs or not entry:
                continue
            facts = [f for f in (getattr(entry, "facts", []) or []) if _clean_line(f)]
            key_finding = _guardrail_text(_clean_line(next((f for f in facts if not _is_meta_language(f)), facts[0] if facts else "")), supported_injury=supported_injury)
            dedupe = _dedupe_key(key_finding)
            if not key_finding or _is_pt_aggregate_count_label(key_finding) or _near_duplicate_seen(dedupe, top_seen):
                continue
            top_seen.add(dedupe)
            a = chron_anchor(str(eid))
            manifest.add_chron_anchor(a)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
            pretty_date = _attorney_date_display(getattr(entry, "date_display", ""))
            date_prefix = f"{pretty_date}: " if pretty_date and pretty_date not in {"Undated", "Date not documented"} and not is_sentinel_date(str(getattr(entry, "date_display", ""))) else ""
            top_anchor_rows.append(Paragraph(
                f'<a name="{escape(a)}"/>- {escape(date_prefix + key_finding)} <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            ))
    prioritized_claims = sorted(claim_rows, key=lambda r: (-(int(r.get("selection_score") or 0)), str(r.get("date") or "9999-99-99")))
    for row in prioritized_claims:
        if len(top_anchor_rows) >= 6:
            break
        assertion = _guardrail_text(_clean_line(row.get("assertion")), supported_injury=supported_injury)
        dedupe = _dedupe_key(assertion)
        if not assertion or _is_pt_aggregate_count_label(assertion) or _near_duplicate_seen(dedupe, top_seen):
            continue
        if _is_undermining_or_noise(assertion):
            continue
        refs = _claim_row_citation_refs(row, citations_by_page, single_doc_id)
        if not refs:
            continue
        top_seen.add(dedupe)
        a = chron_anchor(str(row.get("event_id") or f"top_{len(top_anchor_rows)}"))
        manifest.add_chron_anchor(a)
        _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
        row_date = _attorney_date_display(str(row.get("date") or ""))
        date_prefix = f"{row_date}: " if row_date and row_date not in {"Undated", "Date not documented"} and str(row.get("date") or "").lower() != "unknown" else ""
        top_anchor_rows.append(Paragraph(
            f'<a name="{escape(a)}"/>- {escape(date_prefix + assertion)} <font size="8">{escape(cite_text)}</font>',
            bullet_style,
        ))
    if not top_anchor_rows:
        top_anchor_rows.append(Paragraph("- Not available in packet extraction (no citation-supported anchor rows).", bullet_style))
    flowables.extend(top_anchor_rows)

    # Page 2 - Timeline table
    flowables.append(PageBreak())
    flowables.append(Paragraph('<a name="chronology_section_header"/>Medical Timeline (Litigation Ready)', h1_style))
    flowables.extend(_build_timeline_table(
        projection,
        styles,
        manifest,
        event_citations_by_event,
        citations_by_page,
        single_doc_id,
    ))

    # Page 3 - Imaging / Objective / Diagnoses
    flowables.append(PageBreak())
    flowables.append(Paragraph("Imaging & Objective Findings", h1_style))
    img_rows = _manifest_finding_paragraphs(
        rm,
        categories=("imaging",),
        styles=styles,
        manifest=manifest,
        citation_by_id=citation_by_id,
        by_page=citations_by_page,
        single_doc_id=single_doc_id,
        limit=8,
        include_secondary=False,
        headline_only=True,
        exclude_semantic_families=snapshot_promoted_semantic_families,
    )
    if not img_rows:
        img_rows = _build_claim_row_sections(ext, styles, manifest, citations_by_page, single_doc_id, section_kind="imaging")
    flowables.extend(_paragraph_list_section("Imaging Summary", img_rows, h2_style) or [Paragraph("Imaging Summary", h2_style), Paragraph("No citation-anchored imaging item qualified for summary display.", normal_style)])
    img_secondary_rows = _manifest_finding_paragraphs(
        rm,
        categories=("imaging",),
        styles=styles,
        manifest=manifest,
        citation_by_id=citation_by_id,
        by_page=citations_by_page,
        single_doc_id=single_doc_id,
        limit=4,
        include_secondary=False,
        headline_only=False,
    )
    if img_secondary_rows:
        flowables.append(Paragraph("Secondary / Non-Headline Imaging Observations", h2_style))
        flowables.extend(img_secondary_rows)
    obj_rows = _manifest_finding_paragraphs(
        rm,
        categories=("objective_deficit",),
        styles=styles,
        manifest=manifest,
        citation_by_id=citation_by_id,
        by_page=citations_by_page,
        single_doc_id=single_doc_id,
        limit=8,
        exclude_semantic_families=snapshot_promoted_semantic_families,
    )
    if not obj_rows:
        obj_rows = _build_claim_row_sections(ext, styles, manifest, citations_by_page, single_doc_id, section_kind="objective")
    if not obj_rows and raw_events:
        fallback: list[Paragraph] = []
        for evt in raw_events:
            text = " ".join(str(getattr(f, "text", "") or "") for f in (getattr(evt, "exam_findings", []) or []) + (getattr(evt, "facts", []) or []))
            if not re.search(r"\b(4/5|weakness|strength|spasm|lordosis|rom|reflex)\b", text, re.I):
                continue
            refs = event_citations_by_event.get(str(evt.event_id), [])
            if not refs:
                continue
            first_fact = _first_supported_fact(evt)
            if _is_pt_aggregate_count_label(first_fact):
                continue
            a = chron_anchor(str(evt.event_id))
            manifest.add_chron_anchor(a)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
            fallback.append(Paragraph(f'<a name="{escape(a)}"/>- {escape(first_fact)}<br/><font size="8">{escape(cite_text)}</font>', bullet_style))
            if len(fallback) >= 6:
                break
        obj_rows = fallback
    flowables.extend(_paragraph_list_section("Objective Exam Findings", obj_rows, h2_style) or [Paragraph("Objective Exam Findings", h2_style), Paragraph("No citation-anchored objective finding qualified for summary display.", normal_style)])
    dx_rows = _manifest_finding_paragraphs(
        rm,
        categories=("diagnosis", "procedure"),
        styles=styles,
        manifest=manifest,
        citation_by_id=citation_by_id,
        by_page=citations_by_page,
        single_doc_id=single_doc_id,
        limit=10,
        exclude_semantic_families=snapshot_promoted_semantic_families,
    )
    if not dx_rows:
        dx_rows = _build_claim_row_sections(ext, styles, manifest, citations_by_page, single_doc_id, section_kind="dx")
    flowables.extend(_paragraph_list_section("Diagnoses / Assessment", dx_rows, h2_style) or [Paragraph("Diagnoses / Assessment", h2_style), Paragraph("No citation-anchored diagnosis/assessment item qualified for summary display.", normal_style)])

    # Page 4 - Treatment course & compliance
    flowables.append(PageBreak())
    flowables.append(Paragraph("Treatment Course & Compliance", h1_style))
    care_lines: list[tuple[str, list[dict[str, Any]]]] = []
    if care_window:
        care_lines.append((f"Care duration (export window): {care_window[0].isoformat()} to {care_window[1].isoformat()}", []))
    if pt_summary.get("visits") is not None:
        visits_line = f"PT visits (Verified): {pt_summary['visits']} encounters"
        if pt_summary.get("start") and pt_summary.get("end"):
            visits_line += f" ({pt_summary['start']} to {pt_summary['end']})"
        rm_pt_refs = _refs_from_citation_ids([str(c) for c in (rm_pt.get("citation_ids") or [])], citation_by_id) if isinstance(rm_pt, dict) else []
        if not rm_pt_refs and pt_payload.get("encounters"):
            for row in (pt_payload.get("encounters") or [])[:4]:
                rm_pt_refs.extend(_pt_ledger_refs(row, citation_by_id))
            # keep unique refs by citation label target
            seen_keys: set[str] = set()
            deduped_refs = []
            for ref in rm_pt_refs:
                key = f"{ref.get('doc_id')}|{ref.get('local_page')}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped_refs.append(ref)
            rm_pt_refs = deduped_refs[:8]
        care_lines.append((visits_line, rm_pt_refs))
    if pt_payload.get("reported_max") is not None:
        rep_min = pt_payload.get("reported_min")
        rep_max = pt_payload.get("reported_max")
        rep_label = str(rep_max) if rep_min == rep_max else f"{rep_min}-{rep_max}"
        rep_refs: list[dict[str, Any]] = []
        for row in (pt_payload.get("reported") or [])[:6]:
            rep_refs.extend(_pt_ledger_refs(row, citation_by_id))
        care_lines.append((f"PT visits (Reported in records): {rep_label}", rep_refs[:8]))
        care_lines.append(("Reported totals are summaries; verified counts are enumerated dated encounters present in this packet.", []))
    if isinstance(rm_pt, dict) and _clean_line(rm_pt.get("reconciliation_note")):
        care_lines.append((f"PT count reconciliation: {_clean_line(rm_pt.get('reconciliation_note'))}", _refs_from_citation_ids([str(c) for c in (rm_pt.get('citation_ids') or [])], citation_by_id)))
    if lsv1_gap_gt45:
        care_lines.append((f"Treatment gaps detected (max gap: {lsv1_max_gap_days} days)", []))
    elif global_gaps or raw_gaps_gt45:
        gap_count_display = max(len(global_gaps), len(raw_gaps_gt45))
        care_lines.append((f"Treatment gaps >45 days identified: {gap_count_display} (see chronology and appendices)", []))
    else:
        refs = []
        if dated_events:
            refs = (event_citations_by_event.get(str(dated_events[0].event_id), []) + event_citations_by_event.get(str(dated_events[-1].event_id), []))[:6]
        care_lines.append(("No treatment gaps >45 days detected.", refs))
    for idx, (line, refs) in enumerate(care_lines):
        if refs:
            a = chron_anchor(f"careline_{idx}")
            manifest.add_chron_anchor(a)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
            flowables.append(Paragraph(f'<a name="{escape(a)}"/>- {escape(line)} <font size="8">{escape(cite_text)}</font>', normal_style))
        else:
            flowables.append(Paragraph(f"- {escape(line)}", normal_style))
    if pt_payload.get("reported_max") is not None:
        flowables.append(Spacer(1, 0.05 * inch))
        flowables.extend(_build_pt_reconciliation_table(pt_payload, styles))
        if pt_payload.get("severe_variance_flag"):
            redflag = ParagraphStyle(
                "PTVarianceRedFlag",
                parent=normal_style,
                backColor=colors.HexColor("#FEF2F2"),
                borderColor=colors.HexColor("#EF4444"),
                borderWidth=0.6,
                borderPadding=5,
                textColor=colors.HexColor("#991B1B"),
                spaceBefore=4,
                spaceAfter=6,
            )
            flowables.append(Paragraph(
                f"<b>PT count variance:</b> reported {int(pt_payload.get('reported_max') or 0)}, verified {int(pt_payload.get('verified_count') or 0)}. Review packet completeness and PT ledger reconciliation before attorney use.",
                redflag,
            ))
    flowables.append(Spacer(1, 0.08 * inch))

    discharge_rows = []
    for evt in raw_events:
        evtype = str(getattr(getattr(evt, "event_type", None), "value", getattr(evt, "event_type", "")))
        if evtype not in {"discharge", "hospital_discharge"}:
            continue
        refs = event_citations_by_event.get(str(evt.event_id), [])
        if not refs:
            continue
        a = chron_anchor(str(evt.event_id))
        manifest.add_chron_anchor(a)
        _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
        discharge_rows.append(Paragraph(
            f'<a name="{escape(a)}"/>- {_event_date_label(evt)} | {_first_supported_fact(evt)} <font size="8">{escape(cite_text)}</font>',
            bullet_style,
        ))
        if len(discharge_rows) >= 4:
            break
    flowables.append(Paragraph("Discharge / Outcome Notes", h2_style))
    if discharge_rows:
        flowables.extend(discharge_rows)
    else:
        flowables.append(Paragraph("Not available in packet extraction.", normal_style))

    # Page 5 - Billing / Specials
    flowables.append(PageBreak())
    flowables.extend(build_billing_specials_section(
        specials_summary,
        styles,
        manifest=manifest,
        citation_by_id=citation_by_id,
        billing_completeness=(str(rm.get("billing_completeness")) if isinstance(rm, dict) and rm.get("billing_completeness") else None),
    ))

    # Appendix
    flowables.append(PageBreak())
    flowables.append(Paragraph("Citation Index & Record Appendix", h1_style))
    pt_ledger_flowables = _build_pt_visit_ledger_section(
        pt_payload,
        styles=styles,
        manifest=manifest,
        citation_by_id=citation_by_id,
    )
    if pt_ledger_flowables:
        flowables.extend(pt_ledger_flowables)
        flowables.append(Spacer(1, 0.08 * inch))
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
    manifest_bytes: bytes | None = None
    if run_id or manifest.forward_links:
        from dataclasses import asdict
        import json
        manifest_payload = asdict(manifest)
        if evidence_graph_payload and isinstance(evidence_graph_payload, dict):
            ext_for_manifest = _ext_payload(evidence_graph_payload)
            if "quality_gate" in ext_for_manifest:
                manifest_payload["quality_gate"] = ext_for_manifest.get("quality_gate")
        if moat_stats:
            manifest_payload["moat_quality_stats"] = moat_stats
        manifest_bytes = json.dumps(manifest_payload, indent=2).encode("utf-8")
        if run_id:
            from packages.shared.storage import save_artifact
            save_artifact(run_id, "render_manifest.json", manifest_bytes)
    pdf_bytes = buffer.getvalue()
    try:
        from apps.worker.steps.export_render.pdf_linker import add_internal_links
        if manifest.forward_links and manifest_bytes:
            import json
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
