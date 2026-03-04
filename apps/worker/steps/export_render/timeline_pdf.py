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
    ATTORNEY_UNDATED_LABEL,
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
from apps.worker.steps.export_render.gap_utils import build_gap_anchor_metadata_rows
from apps.worker.steps.export_render.render_manifest import (
    RenderManifest,
    chron_anchor,
    appendix_anchor,
)
from apps.worker.steps.export_render.moat_section import build_moat_section_flowables
from apps.worker.steps.export_render.copy_translations import (
    attorney_tier_label,
    build_defense_vulnerabilities,
)
from apps.worker.steps.export_render.mediation_sections import (
    build_mediation_sections,
    build_mediation_exec_summary_items,
    run_mediation_structural_gate,
)
from packages.shared.utils.scoring_utils import (
    bucket_for_required_coverage as _bucket_for_required_coverage,
    classify_projection_entry as _classify_projection_entry,
)

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
        summary += "Medical billing totals are not established in available records.\n"

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


def _entry_fact_flag_pairs(entry: Any) -> list[tuple[str, bool]]:
    facts = [_clean_line(f) for f in (getattr(entry, "facts", []) or []) if _clean_line(f)]
    flags = list(getattr(entry, "verbatim_flags", []) or [])
    if len(flags) < len(facts):
        flags.extend([False] * (len(facts) - len(flags)))
    return list(zip(facts, flags[: len(facts)]))


def _pick_key_finding_page_anchored(
    candidate_pairs: list[tuple[str, bool]],
    refs: list[dict],
    citation_by_id: dict,
) -> tuple[str, bool]:
    """
    INV-Q4 (Pass 045): Select the key finding fact that is best anchored to the
    event's primary citation page(s). Scores each candidate fact by token overlap
    with the citation snippets for that event. Falls back to candidate_pairs[0]
    when no match is found.

    This prevents the bug where the first fact in the list was always chosen
    regardless of which date/page it came from — e.g. a 2013 ED row showing
    text from 2014 because a later citation happened to be listed first.
    """
    if not candidate_pairs:
        return ("", False)
    if len(candidate_pairs) == 1:
        return candidate_pairs[0]

    # Build combined snippet text from all citation pages for this event.
    combined_snippets: list[str] = []
    for ref in refs or []:
        # refs are dicts from event_citations_by_event; look up the full citation snippet.
        cid = str(ref.get("citation_id") or ref.get("id") or "").strip()
        if cid and citation_by_id:
            cit = citation_by_id.get(cid)
            if cit:
                sn = str(getattr(cit, "snippet", "") or "").strip()
                if sn:
                    combined_snippets.append(sn.lower())

    if not combined_snippets:
        # No snippet data available — fall back to original order.
        return candidate_pairs[0]

    page_corpus = " ".join(combined_snippets)
    page_tokens = set(re.findall(r"\b[a-z]{4,}\b", page_corpus))

    best_pair = candidate_pairs[0]
    best_score = -1
    for fact_text, is_verbatim in candidate_pairs:
        if not fact_text:
            continue
        fact_tokens = set(re.findall(r"\b[a-z]{4,}\b", fact_text.lower()))
        if not fact_tokens:
            continue
        overlap = len(fact_tokens & page_tokens)
        # Normalised by fact token count to prefer concise, well-matched facts.
        score = overlap / max(1, len(fact_tokens))
        if score > best_score:
            best_score = score
            best_pair = (fact_text, is_verbatim)

    return best_pair


def _quote_if_verbatim(text: str, is_verbatim: bool) -> str:
    cleaned = _clean_line(text)
    if not cleaned:
        return ""
    return f'"{cleaned}"' if is_verbatim else cleaned


def _attorney_placeholder_text(text: str | None) -> str:
    s = _clean_line(text)
    if not s:
        return ""
    low = s.lower()
    if low == "see patient header":
        return "Patient name not reliably extracted from packet"
    return s


def _mrn_display_from_citations(citations: list[Citation] | None) -> str | None:
    for c in (citations or []):
        sn = _clean_line(str(getattr(c, "snippet", "") or ""))
        if not sn:
            continue
        m = re.search(r"\b(?:mrn|medical record number|account number|acct(?:ount)?\s*#?)\s*[:#-]?\s*([a-z0-9-]{4,})\b", sn, re.I)
        if not m:
            continue
        token = re.sub(r"[^A-Za-z0-9]", "", m.group(1))
        if not token:
            continue
        tail = token[-4:] if len(token) > 4 else token
        return f"Patient identifier: MRN ending {tail}"
    return None


def _display_matter_title(value: str | None) -> str:
    s = _clean_line(value)
    if not s:
        return "Medical Chronology"
    # Clean eval/debug suffixes from attorney-facing display surfaces.
    s = re.sub(r"\bchronology\s+eval\b", "", s, flags=re.I)
    s = re.sub(r"\s*[-:|]+\s*$", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s or "Medical Chronology"


def _is_undermining_or_noise(text: str) -> bool:
    blob = (text or "").lower()
    if not blob:
        return True
    if any(p in blob for p in _FRONT_PAGE_BANNED_PHRASES):
        return True
    if "(cid:" in blob:
        return True
    if re.search(r"\b(unremarkable|no acute fracture|no dislocation|no significant degenerative)\b", blob):
        return True
    if re.search(r"\btotal amount:\s*[$]?\d", blob):
        return True
    if re.search(r"\bfax id\b", blob):
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
        return ATTORNEY_UNDATED_LABEL
    label = re.sub(r"\s*\(time not documented\)\s*", "", label or "").strip()
    return label or ATTORNEY_UNDATED_LABEL


def _attorney_date_display(label: str | None) -> str:
    s = _attorney_placeholder_text(label)
    if not s:
        return ATTORNEY_UNDATED_LABEL
    s = re.sub(r"\s*\(time not documented\)\s*", "", s, flags=re.I).strip()
    if is_sentinel_date(s) or s.strip().lower() in {"undated", "date not documented"}:
        return ATTORNEY_UNDATED_LABEL
    return s or ATTORNEY_UNDATED_LABEL


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
        return links, "Citation(s): Citation not established in available records"
    return links, "Citation(s): " + " ".join(f"[{l}]" for l in labels)


def _top10_inline_citation_suffix(refs: list[dict[str, Any]]) -> str:
    pages: list[int] = []
    seen: set[int] = set()
    for ref in refs:
        page_no = int(ref.get("local_page") or ref.get("global_page") or 0)
        if page_no <= 0 or page_no in seen:
            continue
        seen.add(page_no)
        pages.append(page_no)
    if not pages:
        return ""
    return " " + " ".join(f"[p. {p}]" for p in pages[:4])


def _paragraph_list_section(title: str, rows: list[Paragraph], title_style: Any) -> list:
    if not rows:
        return []
    return [Paragraph(title, title_style), Spacer(1, 0.06 * inch), *rows, Spacer(1, 0.08 * inch)]


def _safe_money(v: Any) -> str:
    try:
        if v is None or str(v).strip() == "":
            return "Not established"
        return f"${float(v):,.2f}"
    except Exception:
        return "Not established"


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


def _export_status_internal(ext: dict, rm: dict) -> str:
    """
    Conservative export status label for attorney-facing PDF header.

    Render runs before final run-row status persistence in some paths, so default to
    REVIEW_RECOMMENDED unless we have strong evidence the export is clean.
    """
    inv = ext.get("sprint4d_invariants") if isinstance(ext, dict) else None
    if isinstance(inv, dict):
        if bool(inv.get("ED_EXISTS_BUT_NOT_RENDERED")):
            return "BLOCKED"
        if bool(inv.get("PAGE1_PROMOTED_PARITY_FAILURE")):
            return "BLOCKED"
        if bool(inv.get("VERBATIM_REQUIRED_MISSING")):
            return "BLOCKED"
        missing = [str(x).strip().lower() for x in (inv.get("missing_required_buckets") or []) if str(x).strip()]
        if missing:
            return "BLOCKED"
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
                date_anom = pt_recon.get("date_concentration_anomaly") if isinstance(pt_recon.get("date_concentration_anomaly"), dict) else {}
                if bool(date_anom.get("triggered")) and status == "VERIFIED":
                    status = "REVIEW_RECOMMENDED"
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


def _export_status_label(ext: dict, rm: dict) -> str:
    return attorney_tier_label(_export_status_internal(ext, rm))


def _litigation_safe_payload(ext: dict) -> dict[str, Any]:
    payload = ext.get("litigation_safe_v1") if isinstance(ext, dict) else None
    return payload if isinstance(payload, dict) else {}


def _claim_context_alignment_payload(ext: dict) -> dict[str, Any]:
    payload = ext.get("claim_context_alignment") if isinstance(ext, dict) else None
    return payload if isinstance(payload, dict) else {}


def _mechanism_alignment_status(cca: dict[str, Any], rm: dict[str, Any]) -> tuple[str | None, str | None]:
    mechanism = (rm.get("mechanism") or {}) if isinstance(rm, dict) else {}
    value = _clean_line((mechanism or {}).get("value"))
    cits = tuple(sorted(str(c).strip() for c in ((mechanism or {}).get("citation_ids") or []) if str(c).strip()))
    if not value:
        return (None, None)
    for row in (cca.get("claims") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("claim_type") or "").strip().lower() != "mechanism":
            continue
        if _clean_line(row.get("claim_text")) != value:
            continue
        row_cits = tuple(sorted(str(c).strip() for c in (row.get("citations") or []) if str(c).strip()))
        if cits and row_cits and cits != row_cits:
            continue
        return (str(row.get("severity") or "PASS").upper(), str(row.get("claim_id") or "").strip() or None)
    return (None, None)


def _mechanism_blocked_in_alignment(cca: dict[str, Any]) -> bool:
    for f in (cca.get("failures") or []):
        if not isinstance(f, dict):
            continue
        if str(f.get("severity") or "").strip().upper() != "BLOCKED":
            continue
        ctype = str(f.get("claim_type") or "").strip().lower()
        if ctype == "mechanism":
            return True
        for cf in (f.get("claim_failures") or []):
            if isinstance(cf, dict) and str(cf.get("claim_type") or "").strip().lower() == "mechanism":
                return True
    return False


def _litigation_gap_summary(lsv1: dict[str, Any]) -> tuple[bool, int]:
    computed = lsv1.get("computed") if isinstance(lsv1.get("computed"), dict) else {}
    try:
        max_gap_days = int(computed.get("max_gap_days") or 0)
    except Exception:
        max_gap_days = 0
    return (max_gap_days > 45, max_gap_days)


def _pt_evidence_payload(ext: dict) -> dict[str, Any]:
    pt_encounters = [
        r for r in (ext.get("pt_encounters") or [])
        if isinstance(r, dict) and str(r.get("source") or "primary") == "primary"
    ]
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
        "ledger_rows": len(pt_encounters),
        "count_source": ("ledger" if pt_encounters else ("reconciliation" if pt_recon else "event_fallback")),
        "reported_vals": reported_vals,
        "reported_min": (min(reported_vals) if reported_vals else None),
        "reported_max": (max(reported_vals) if reported_vals else None),
        "variance_flag": bool(pt_recon.get("variance_flag")),
        "severe_variance_flag": bool(pt_recon.get("severe_variance_flag")),
    }


def _pt_verified_display_allowed(pt_payload: dict[str, Any]) -> bool:
    ledger_rows = int(pt_payload.get("ledger_rows") or 0)
    verified_count = int(pt_payload.get("verified_count") or 0)
    return ledger_rows > 0 and verified_count > 0 and ledger_rows == verified_count


def _pt_display_label(pt_payload: dict[str, Any]) -> str:
    return "Verified" if _pt_verified_display_allowed(pt_payload) else "Reported"


def _pt_reported_numeric_allowed(pt_payload: dict[str, Any]) -> bool:
    """
    Reported PT numeric counts are only attorney-displayable once we have at least
    some primary ledger-backed verification in this packet.
    """
    ledger_rows = int(pt_payload.get("ledger_rows") or 0)
    verified_count = int(pt_payload.get("verified_count") or 0)
    return ledger_rows > 0 and verified_count > 0


def _pt_unverified_disclosure_line(pt_payload: dict[str, Any]) -> str:
    reported_max = int(pt_payload.get("reported_max") or 0)
    if reported_max > 10:
        return "High-volume PT mentioned in records; ledger verification required."
    return "PT volume mentioned in records; ledger verification required."


def _enforce_export_cleanroom(
    pdf_bytes: bytes,
    *,
    include_internal_review_sections: bool = False,
    export_mode: str = "INTERNAL",
) -> None:
    """
    Block contaminated export output instead of post-hoc redaction.
    """
    if include_internal_review_sections:
        return
    banned_patterns = [
        re.compile(r"\bNot Yet Litigation-Safe\b", re.I),
        re.compile(r"\bAttorney-facing chronology\b", re.I),
        re.compile(r"\bRecommended attorney action\b", re.I),
        re.compile(r"\bDefense vulnerabilities\b", re.I),
        re.compile(r"\bCase Readiness\b", re.I),
        re.compile(r"\bdefense may exploit\b", re.I),
        re.compile(r"\bChronology Eval\b", re.I),
        re.compile(r"\bCLAIM_CONTEXT_ALIGNMENT\b", re.I),
        re.compile(r"\bsemantic_mismatch\b", re.I),
        re.compile(r"\bpage_type_mismatch\b", re.I),
        re.compile(r"\bQA_[A-Za-z0-9_]+\b", re.I),
        re.compile(r"\bAR_[A-Za-z0-9_]+\b", re.I),
    ]
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(pdf_bytes))
        # Ignore optional eval validation cover page; enforce on export body pages.
        pages = list(reader.pages)
        body_pages = pages[1:] if len(pages) > 1 else pages
        body_text = "\n".join((p.extract_text() or "") for p in body_pages)
    except Exception:
        body_text = ""
    hits: list[str] = []
    for pat in banned_patterns:
        for m in pat.finditer(body_text or ""):
            hits.append(m.group(0))
    mode = str(export_mode or "INTERNAL").strip().upper()
    if mode == "MEDIATION":
        mediation_banned = [
            re.compile(r"\bCASE SEVERITY INDEX\b", re.I),
            re.compile(r"\bSettlement Intelligence\b", re.I),
            re.compile(r"\bSLI\b", re.I),
            re.compile(r"\bRisk-adjusted\b", re.I),
            re.compile(r"\bbase_csi\b", re.I),
            re.compile(r"\brisk_adjusted\b", re.I),
            re.compile(r"\bscore_0_100\b", re.I),
            re.compile(r"\bweights\b", re.I),
            re.compile(r"\bpenalty_total\b", re.I),
        ]
        for pat in mediation_banned:
            for m in pat.finditer(body_text or ""):
                hits.append(m.group(0))
        mediation_value_patterns = [
            re.compile(r"(?i)(severity|csi|case severity|risk-adjusted).{0,40}\b\d+(?:\.\d+)?/10\b"),
            re.compile(r"(?i)\b\d+(?:\.\d+)?/10\b.{0,40}(severity|csi|case severity|risk-adjusted)"),
        ]
        for pat in mediation_value_patterns:
            for m in pat.finditer(body_text or ""):
                hits.append(m.group(0))
    if hits:
        uniq = ", ".join(sorted(set(hits))[:6])
        raise RuntimeError(f"EXPORT_CLEANROOM_BLOCKED: banned phrase(s) detected in export body: {uniq}")


_MEDIATION_BANNED_FIELDS = {
    "base_csi",
    "risk_adjusted_csi",
    "score_0_100",
    "weights",
    "penalty_total",
    "floor_applied",
    "ceiling_applied",
    "case_severity_index",
}


def _assert_mediation_input_safe(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            key = str(k)
            low = key.strip().lower()
            if (
                key in _MEDIATION_BANNED_FIELDS
                or "settlement" in low
                or low.startswith("sli")
                or "valuation" in low
                or "negotiation_posture" in low
            ):
                raise RuntimeError(f"MEDIATION_RENDER_INPUT_BLOCKED: banned field '{key}' at {path}")
            _assert_mediation_input_safe(v, f"{path}.{key}")
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            _assert_mediation_input_safe(item, f"{path}[{idx}]")


def _gap_anchor_line(
    gap_anchor_meta: list[dict[str, Any]],
    citation_by_id: dict[str, dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    for gap in gap_anchor_meta:
        if not isinstance(gap, dict):
            continue
        gap_days = int(gap.get("gap_days") or 0)
        if gap_days <= 45:
            continue
        refs = _refs_from_citation_ids([str(c) for c in (gap.get("citation_ids") or [])], citation_by_id)
        if len(refs) >= 2 and bool(gap.get("anchors_complete")):
            sp = gap.get("gap_start_page")
            ep = gap.get("gap_end_page")
            page_phrase = f" between p. {sp} and p. {ep}" if sp and ep else ""
            return (f"Treatment gap detected ({gap_days} days){page_phrase}.", refs[:6])
    return (None, [])


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
            Paragraph(f'<a name="{escape(row_anchor)}"/>{escape(str(row.get("encounter_date") or ATTORNEY_UNDATED_LABEL))}', small),
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
    internal_status = str(lsv1.get("status") or "REVIEW_RECOMMENDED").strip().upper() or "REVIEW_RECOMMENDED"
    label = attorney_tier_label(internal_status)
    if internal_status == "BLOCKED":
        bg = "#FEF2F2"
        fg = "#991B1B"
        border = "#FCA5A5"
    elif internal_status == "VERIFIED":
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
    rows: list = [Paragraph("Case Readiness Review", h2), Paragraph(f"<b>Status:</b> {escape(label)}", badge)]
    vulnerabilities = build_defense_vulnerabilities(lsv1)
    if vulnerabilities:
        severity_by_code = {
            "MECHANISM_OR_DIAGNOSIS_UNSUPPORTED": "High",
            "INTERNAL_CONTRADICTION": "High",
            "GAP_STATEMENT_INCONSISTENT": "High",
            "BILLING_IMPLIED_COMPLETE": "High",
            "PROCEDURE_DATE_MISSING": "Moderate",
        }
        rank_order = {"High": 0, "Moderate": 1, "Low": 2}
        sev_counts = {"High": 0, "Moderate": 0, "Low": 0}
        ranked = []
        for item in vulnerabilities:
            sev = severity_by_code.get(str(item.get("code") or ""), "Moderate")
            sev_counts[sev] += 1
            ranked.append((rank_order.get(sev, 1), sev, item))
        ranked.sort(key=lambda x: (x[0], str((x[2] or {}).get("display_title") or "")))
        rows.append(Paragraph("<b>Defense Vulnerabilities Identified</b>", normal))
        rows.append(Paragraph("<b>Attorney Review Summary</b>", normal))
        rows.append(Paragraph(
            escape(
                f"Total vulnerabilities: {len(vulnerabilities)} | "
                f"High: {sev_counts['High']} | Moderate: {sev_counts['Moderate']} | Low: {sev_counts['Low']}"
            ),
            bullet,
        ))
        top_actions = [it for _rk, sev, it in ranked[:3]]
        for idx, item in enumerate(top_actions, start=1):
            title = str(item.get("display_title") or "Risk").strip()
            action = str(item.get("recommended_action") or "").strip()
            summary = f"Top {idx} risk: {title}"
            if action:
                summary += f" | Action: {action}"
            rows.append(Paragraph(escape(summary), bullet))
        for item in vulnerabilities:
            title = str(item.get("display_title") or "").strip()
            attorney_message = str(item.get("attorney_message") or "").strip()
            defense_risk = str(item.get("defense_risk") or "").strip()
            recommended_action = str(item.get("recommended_action") or "").strip()
            if title:
                rows.append(Paragraph(f"- <b>{escape(title)}</b>", bullet))
            if attorney_message:
                rows.append(Paragraph(escape(f"What was detected: {attorney_message}"), bullet))
            if defense_risk:
                rows.append(Paragraph(escape(f"Why defense may exploit it: {defense_risk}"), bullet))
            if recommended_action:
                rows.append(Paragraph(escape(f"Recommended attorney action: {recommended_action}"), bullet))
    else:
        rows.append(Paragraph("No material documentation conflicts detected in cited records.", normal))
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


def _manifest_promoted_items(rm: dict) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in (rm.get("promoted_findings") or []):
        if not isinstance(item, dict):
            continue
        if not (item.get("citation_ids") or []):
            continue
        items.append(item)
    return items


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


def _pain_score(text: str | None) -> str | None:
    s = _clean_line(text or "")
    if not s:
        return None
    m = re.search(r"\b(\d{1,2})\s*/\s*10\b", s, re.I)
    if not m:
        return None
    return f"{int(m.group(1))}/10"


def _is_weak_facility_pain_label(text: str | None) -> bool:
    s = _clean_line(text or "")
    if not s:
        return False
    if not _pain_score(s):
        return False
    if not re.search(r"\b(hospital|center|clinic|medical)\b", s, re.I):
        return False
    return not re.search(r"\b(pain|tender|spasm|radicul|diagnos|impression|injury|fracture|rom)\b", s, re.I)


def _is_financial_amount_label(text: str | None) -> bool:
    s = _clean_line(text or "")
    if not s:
        return False
    return bool(re.search(r"\b(total amount|balance|charges?)\b", s, re.I) and re.search(r"\$\s*\d", s, re.I))


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
    required_bucket_event_ids: dict[str, set[str]] | None = None,
    required_bucket_pages: dict[str, set[int]] | None = None,
    timeline_audit: dict[str, Any] | None = None,
    unresolved_invasive_rows: list[dict[str, Any]] | None = None,
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
        entry_bucket = _bucket_for_required_coverage(entry)
        is_ed_row = bool(
            entry_bucket == "ed"
            or
            "emergency" in etype
            or re.search(r"\b(ed notes?|emergency department|emergency room|triage|chief complaint|hpi|rear[- ]end|motor vehicle collision|mvc|mva)\b", finding_low)
        )
        if "general hospital" in finding_low:
            return "General Hospital & Trauma Center"
        if provider_low in {"unknown", "provider not stated"}:
            return "ED Facility Unknown" if is_ed_row else "Provider not clearly identified"
        # Do not present PT provider names as if they authored imaging/ER/procedure records.
        if re.search(r"\b(physical therapy|\\bpt\\b)\b", provider_low):
            if any(x in etype for x in ("imaging", "emergency", "procedure")):
                return "Provider not clearly identified"
            if "clinical note" in etype and "physical therapy" not in finding_low and "pt " not in f" {finding_low} ":
                return "Provider not clearly identified"
        if provider and provider == provider.lower() and re.fullmatch(r"[a-z0-9&'./ -]+", provider):
            provider = " ".join(w.capitalize() if w not in {"of", "and", "the"} else w for w in provider.split())
        return provider or "Provider not clearly identified"

    required_bucket_event_ids = required_bucket_event_ids or {}
    required_bucket_pages = required_bucket_pages or {}
    required_event_to_bucket: dict[str, str] = {}
    for b, ids in required_bucket_event_ids.items():
        for eid in ids:
            required_event_to_bucket[str(eid)] = str(b)
    if timeline_audit is not None:
        timeline_audit.setdefault("dropped", [])
        timeline_audit.setdefault("rendered_event_ids", [])
        timeline_audit.setdefault("rendered_buckets", [])
    rendered_ids: set[str] = set()

    def _drop(eid: str, reason: str) -> None:
        if timeline_audit is None:
            return
        bucket = required_event_to_bucket.get(str(eid))
        timeline_audit["dropped"].append({"event_id": str(eid), "reason": reason, "bucket": bucket})

    for entry in scored:
        eid = str(getattr(entry, "event_id", "") or "")
        entry_bucket = _bucket_for_required_coverage(entry)
        entry_pages = {int(p) for p in re.findall(r"\bp\.\s*(\d+)\b", str(getattr(entry, "citation_display", "") or ""), re.I)}
        overlap_buckets = sorted(
            [b for b, pages in required_bucket_pages.items() if pages and entry_pages.intersection(set(pages))]
        )
        inferred_required_bucket = overlap_buckets[0] if overlap_buckets else None
        is_required = (
            eid in required_event_to_bucket
            or entry_bucket in {"ed", "pt_eval"}
            or inferred_required_bucket in {"ed", "pt_eval"}
        )
        if not getattr(entry, "citation_display", ""):
            _drop(eid, "DROPPED_MISSING_CITATION_DISPLAY")
            continue
        etype_low = str(entry.event_type_display or "").lower()
        if "billing" in etype_low:
            _drop(eid, "DROPPED_BILLING_ROW")
            continue
        date_cell = _attorney_date_display(getattr(entry, "date_display", ""))
        entry_family = _classify_projection_entry(entry)
        if entry_family == "surgery_procedure" and date_cell in {"Undated", "Date not documented", ATTORNEY_UNDATED_LABEL}:
            refs = citation_refs_by_event.get(str(entry.event_id), [])
            if not refs and getattr(entry, "citation_display", "") and by_page is not None:
                refs = _claim_row_citation_refs({"citations": [c.strip() for c in str(entry.citation_display).split(",")]}, by_page, single_doc_id)
            fact_pairs_undated = _entry_fact_flag_pairs(entry)
            key_finding_undated = fact_pairs_undated[0][0] if fact_pairs_undated else ""
            if unresolved_invasive_rows is not None:
                unresolved_invasive_rows.append(
                    {
                        "event_id": eid,
                        "event_type": _clean_line(entry.event_type_display) or "Procedure/Surgery",
                        "date_display": date_cell,
                        "provider_display": _clean_line(entry.provider_display) or "Provider not clearly identified",
                        "key_finding": _clean_line(key_finding_undated),
                        "refs": refs[:8],
                    }
                )
            _drop(eid, "DROPPED_UNDATED_INVASIVE_MAIN_TIMELINE")
            continue
        fact_pairs = _entry_fact_flag_pairs(entry)
        facts = [f for f, _is_verbatim in fact_pairs]
        candidate_pairs = [(f, is_verbatim) for f, is_verbatim in fact_pairs if not _is_meta_language(f)]
        key_finding = ""
        key_is_verbatim = False
        for fact_text, is_verbatim in candidate_pairs:
            if not _is_generic_timeline_fact(fact_text):
                key_finding = fact_text
                key_is_verbatim = is_verbatim
                break
        if not key_finding and candidate_pairs:
            key_finding, key_is_verbatim = candidate_pairs[0]
        if not key_finding and is_required and fact_pairs:
            key_finding, key_is_verbatim = fact_pairs[0]
        if not key_finding:
            _drop(eid, "DROPPED_NO_KEY_FINDING")
            continue
        if re.search(r"\bAggregated PT sessions\b", key_finding, re.I):
            # Aggregated PT counts are secondary evidence and should not appear as unlabeled timeline facts.
            _drop(eid, "DROPPED_AGGREGATE_PT_LABEL")
            continue
        if _is_generic_timeline_fact(key_finding) and not is_required:
            _drop(eid, "DROPPED_GENERIC_FACT")
            continue
        row_key = (entry.date_display, entry.provider_display, entry.event_type_display, key_finding[:120])
        if row_key in seen:
            _drop(eid, "DROPPED_DUPLICATE_ROW_KEY")
            continue
        seen.add(row_key)
        if ("therapy" in etype_low or "pt" in etype_low) and pt_rows >= 6 and not is_required:
            _drop(eid, "DROPPED_PT_ROW_CAP")
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
            _drop(eid, "DROPPED_NO_CITATION_REFS")
            continue
        _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
        if "not established" in cite_text.lower():
            _drop(eid, "DROPPED_CITATION_TEXT_UNAVAILABLE")
            continue
        provider_display = _timeline_provider_display(entry, key_finding)
        rows.append([
            Paragraph(f'<a name="{escape(row_anchor)}"/>{escape(date_cell)}', small),
            Paragraph(escape(provider_display), small),
            Paragraph(escape(_clean_line(entry.event_type_display) or "Event"), small),
            Paragraph(escape(_quote_if_verbatim(key_finding, key_is_verbatim)), small),
            Paragraph(escape(cite_text), small),
        ])
        if timeline_audit is not None:
            timeline_audit["rendered_event_ids"].append(eid)
            rendered_ids.add(eid)
            bucket = required_event_to_bucket.get(eid) or inferred_required_bucket or entry_bucket
            if bucket and bucket not in timeline_audit["rendered_buckets"]:
                timeline_audit["rendered_buckets"].append(bucket)
        if len(rows) >= 38:
            break

    # Terminal required-bucket fallback: force one citation-backed row for missing required buckets.
    rendered_buckets_now = set(timeline_audit.get("rendered_buckets") or []) if timeline_audit is not None else set()
    for req_bucket, req_pages in required_bucket_pages.items():
        if req_bucket not in {"ed", "pt_eval"}:
            continue
        if not req_pages or req_bucket in rendered_buckets_now:
            continue
        forced_entry = None
        for entry in scored:
            eid = str(getattr(entry, "event_id", "") or "")
            if not eid or eid in rendered_ids:
                continue
            entry_pages = {int(p) for p in re.findall(r"\bp\.\s*(\d+)\b", str(getattr(entry, "citation_display", "") or ""), re.I)}
            if not entry_pages.intersection(set(req_pages)):
                continue
            refs = citation_refs_by_event.get(str(entry.event_id), [])
            if not refs and getattr(entry, "citation_display", "") and by_page is not None:
                refs = _claim_row_citation_refs({"citations": [c.strip() for c in str(entry.citation_display).split(",")]}, by_page, single_doc_id)
            if not refs:
                continue
            forced_entry = (entry, refs)
            break
        if not forced_entry:
            continue
        entry, refs = forced_entry
        fact_pairs = _entry_fact_flag_pairs(entry)
        candidate_pairs = [(f, is_verbatim) for f, is_verbatim in fact_pairs if not _is_meta_language(f)]
        if candidate_pairs:
            key_finding, key_is_verbatim = candidate_pairs[0]
        elif fact_pairs:
            key_finding, key_is_verbatim = fact_pairs[0]
        else:
            key_finding, key_is_verbatim = "Cited encounter documented.", False
        row_anchor = chron_anchor(str(entry.event_id))
        if manifest:
            manifest.add_chron_anchor(row_anchor)
        _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
        provider_display = _timeline_provider_display(entry, key_finding)
        date_cell = _attorney_date_display(getattr(entry, "date_display", ""))
        rows.append([
            Paragraph(f'<a name="{escape(row_anchor)}"/>{escape(date_cell)}', small),
            Paragraph(escape(provider_display), small),
            Paragraph(escape(_clean_line(entry.event_type_display) or "Event"), small),
            Paragraph(escape(_quote_if_verbatim(key_finding, key_is_verbatim)), small),
            Paragraph(escape(cite_text), small),
        ])
        rendered_ids.add(str(getattr(entry, "event_id", "") or ""))
        rendered_buckets_now.add(req_bucket)
        if timeline_audit is not None:
            timeline_audit["rendered_event_ids"].append(str(getattr(entry, "event_id", "") or ""))
            if req_bucket not in timeline_audit["rendered_buckets"]:
                timeline_audit["rendered_buckets"].append(req_bucket)
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
        is_verbatim = "VERBATIM" in {str(f).upper() for f in (r.get("flags") or [])}
        rendered_assertion = _quote_if_verbatim(assertion, is_verbatim)
        para = Paragraph(
            f'<a name="{escape(row_anchor)}"/>- {escape(rendered_assertion)}<br/><font size="8">{escape(cite_text)}</font>',
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
        flowables.append(Paragraph("Billing extraction status: Not established from the provided packet.", normal))
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
        data = [["Partial Extracted Charges", "Not established in available records (incomplete billing documentation)."]]
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
            flowables.append(Paragraph("Known line items: Not established from the provided packet.", normal))
        if dropped_uncited_provider_rows:
            logger.info("billing provider rows dropped due to missing citations: %s", dropped_uncited_provider_rows)
    else:
        flowables.append(Paragraph("Known line items: Not established from the provided packet.", normal))

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
    include_internal_review_sections: bool = False,
    export_mode: str = "INTERNAL",
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
    export_mode_norm = str(export_mode or "INTERNAL").strip().upper()
    if export_mode_norm not in {"INTERNAL", "MEDIATION"}:
        export_mode_norm = "INTERNAL"
    if export_mode_norm == "MEDIATION":
        _assert_mediation_input_safe(ext, "extensions")
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

    # Page 1 - Case Snapshot / Analysis
    display_matter_title = _display_matter_title(matter_title)
    flowables = [Paragraph(f"Medical Chronology: {display_matter_title}", title_style)]
    if export_mode_norm == "INTERNAL":
        flowables.append(
            Paragraph(
                "INTERNAL ANALYTICS — NOT FOR EXTERNAL DISTRIBUTION",
                ParagraphStyle(
                    "InternalWarningHeader",
                    parent=normal_style,
                    fontSize=9,
                    textColor=colors.HexColor("#7F1D1D"),
                    backColor=colors.HexColor("#FEE2E2"),
                    borderColor=colors.HexColor("#DC2626"),
                    borderWidth=0.5,
                    borderPadding=4,
                    spaceAfter=6,
                ),
            )
        )
        # Pass 37: Leverage debug block (INTERNAL only)
        _lr_debug = ext.get("leverage_index_result") or {}
        if _lr_debug:
            _csi_overrides = ((ext.get("case_severity_index") or {}).get("override_reasons") or [])
            _debug_lines = [
                "<b>LEVERAGE DEBUG (INTERNAL)</b>",
                f"Band: {_lr_debug.get('band')}  |  Score: {_lr_debug.get('score')}  |  Guard: {_lr_debug.get('guard_status')}",
                f"Reasons: {', '.join(_lr_debug.get('reasons') or [])}",
            ]
            if _csi_overrides:
                _debug_lines.append(f"CSI overrides: {', '.join(_csi_overrides)}")
            flowables.append(Paragraph(
                "<br/>".join(_debug_lines),
                ParagraphStyle(
                    "LeverageDebug",
                    parent=normal_style,
                    fontSize=7.5,
                    fontName="Courier",
                    backColor=colors.HexColor("#F0F9FF"),
                    borderColor=colors.HexColor("#0369A1"),
                    borderWidth=0.5,
                    borderPadding=4,
                    spaceAfter=6,
                ),
            ))
        # Pass 40: Version transparency header (INTERNAL only — reads from pre-computed ext)
        _rm = ext.get("run_metadata") or {}
        _lp = ext.get("leverage_policy") or {}
        _fp_short = (_lp.get("fingerprint") or "")[:16]
        if _rm or _fp_short:
            _version_lines = [
                f"Signal Layer: v{_rm.get('signal_layer_version', '?')}",
                f"Policy: {_lp.get('version', '?')}",
                f"Fingerprint: {_fp_short}...",
                f"Determinism: {_rm.get('determinism_check', '?')}",
            ]
            flowables.append(Paragraph(
                "  |  ".join(_version_lines),
                ParagraphStyle(
                    "VersionHeader",
                    parent=normal_style,
                    fontSize=7,
                    fontName="Courier",
                    textColor=colors.HexColor("#374151"),
                    backColor=colors.HexColor("#F9FAFB"),
                    borderColor=colors.HexColor("#9CA3AF"),
                    borderWidth=0.5,
                    borderPadding=3,
                    spaceAfter=4,
                ),
            ))
    if export_mode_norm == "MEDIATION":
        flowables.append(
            Paragraph(
                "MEDIATION EXPORT (NO VALUATION MODEL)",
                ParagraphStyle(
                    "MediationHeader",
                    parent=normal_style,
                    fontSize=9,
                    textColor=colors.HexColor("#7C2D12"),
                    backColor=colors.HexColor("#FEF3C7"),
                    borderColor=colors.HexColor("#F59E0B"),
                    borderWidth=0.5,
                    borderPadding=4,
                    spaceAfter=6,
                ),
            )
        )
    flowables.append(Paragraph("Medical Chronology Analysis", h1_style))
    if include_internal_review_sections:
        flowables.append(Paragraph("Internal review chronology summary generated from citation-anchored records.", ParagraphStyle("ChronologyAnalysisMeta", parent=normal_style, fontSize=8.5, textColor=colors.HexColor("#475569"), spaceAfter=4)))
    flowables.append(Paragraph("CASE SNAPSHOT (30-SECOND READ)", h1_style))

    patient_label = next((str(getattr(e, "patient_label", "")).strip() for e in projection.entries if str(getattr(e, "patient_label", "")).strip() and "unknown" not in str(getattr(e, "patient_label", "")).lower()), "Patient name not reliably extracted from packet")
    if patient_label.strip().lower() == "see patient header":
        patient_label = "Patient name not reliably extracted from packet"
    if patient_label == "Patient name not reliably extracted from packet":
        mrn_fallback = _mrn_display_from_citations(all_citations)
        if mrn_fallback:
            patient_label = mrn_fallback
    dated_events = [e for e in raw_events if _event_date_bounds(e)[0]]
    dated_events.sort(key=lambda e: _event_date_bounds(e)[0] or date.max)
    doi = (_event_date_bounds(dated_events[0])[0].isoformat() if dated_events else None)
    first_er_for_header = next((e for e in dated_events if str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))) in {"er_visit", "hospital_admission", "hospital_discharge", "inpatient_daily_note"}), None)
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
    if not mechanism:
        for row in list(ext.get("claim_rows") or []):
            if not isinstance(row, dict):
                continue
            if not (row.get("citations") or row.get("citation_ids")):
                continue
            txt = _clean_line(str(row.get("assertion") or row.get("text") or "")).lower()
            if not txt:
                continue
            if "rear-end" in txt or "rear end" in txt:
                mechanism = "rear-end motor vehicle collision"
                break
            if "mva" in txt or "mvc" in txt or "motor vehicle" in txt or "collision" in txt:
                mechanism = "motor vehicle collision"
                break
            if "fall" in txt:
                mechanism = "fall"
                break
    if not mechanism and first_er_for_header:
        refs = event_citations_by_event.get(str(first_er_for_header.event_id), [])[:6]
        blobs: list[str] = []
        for ref in refs:
            try:
                pnum = int(ref.get("local_page") or ref.get("page") or 0)
            except Exception:
                pnum = 0
            for c in (citations_by_page.get(pnum) or []):
                txt = _clean_line(str(c.get("snippet") or c.get("text") or ""))
                if txt:
                    blobs.append(txt.lower())
        merged = " ".join(blobs)
        if "rear-end" in merged or "rear end" in merged:
            mechanism = "rear-end motor vehicle collision"
        elif ("mva" in merged or "mvc" in merged or "motor vehicle" in merged or "collision" in merged):
            mechanism = "motor vehicle collision"
        elif "fall" in merged:
            mechanism = "fall"
    rm_doi = ((rm.get("doi") or {}).get("value") if isinstance(rm, dict) else None)
    rm_doi_source = ((rm.get("doi") or {}).get("source") if isinstance(rm, dict) else None)
    if rm_doi and not is_sentinel_date(rm_doi) and str(rm_doi_source or "").lower() != "not_found":
        doi_display = str(rm_doi)
    else:
        doi_display = doi if doi and not is_sentinel_date(doi) else "Not clearly stated in chart documentation"
    rm_mechanism = ((rm.get("mechanism") or {}).get("value") if isinstance(rm, dict) else None)
    mechanism_display = str(rm_mechanism) if rm_mechanism else (mechanism or "Injury mechanism is not expressly documented in chart notes.")
    export_status_internal = _export_status_internal(ext, rm)
    export_status = attorney_tier_label(export_status_internal)
    if not include_internal_review_sections and export_status in {"Attorney Review Recommended", "Not Yet Litigation-Safe"}:
        export_status = "Action Required"
    cca = _claim_context_alignment_payload(ext)
    mechanism_alignment_status, _mechanism_alignment_claim_id = _mechanism_alignment_status(cca, rm if isinstance(rm, dict) else {})
    if (mechanism_alignment_status == "BLOCKED") or _mechanism_blocked_in_alignment(cca):
        mechanism_display = "Injury mechanism is not expressly documented in chart notes."

    header_rows = [
        ["Case", display_matter_title],
        ["Patient", patient_label],
        ["DOI", doi_display],
        ["Mechanism", mechanism_display],
        ["Readiness Tier", export_status],
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
    if include_internal_review_sections:
        flowables.extend(_build_litigation_safety_check_flowables(lsv1, styles))
        if lsv1:
            flowables.append(Spacer(1, 0.05 * inch))

    # Pass34 Tweak 1: In MEDIATION mode, replace Case Highlights with a deterministic
    # 5-line executive summary. No pain scores, no PT count, no QA notes.
    if export_mode_norm == "MEDIATION":
        _exec_bullet_style = ParagraphStyle("ExecSummaryBullet", parent=normal_style, leftIndent=12, bulletIndent=0, spaceAfter=3)
        _exec_items = build_mediation_exec_summary_items(
            ext=ext,
            rm=rm,
            raw_events=raw_events,
            doi_display=doi_display,
            mechanism_display=mechanism_display,
            specials_summary=specials_summary,
            citation_by_id=citation_by_id,
        )
        for _ei in _exec_items:
            if _ei.support:
                flowables.append(Paragraph(
                    f'- {escape(_ei.label)} <font size="8">{escape(_ei.support)}</font>',
                    _exec_bullet_style,
                ))
            else:
                flowables.append(Paragraph(f"- {escape(_ei.label)}", _exec_bullet_style))
        flowables.append(Spacer(1, 0.1 * inch))

    if export_mode_norm != "MEDIATION":
        flowables.append(Paragraph("Case Highlights", h2_style))
        flowables.append(Paragraph("Emergency department and treatment documentation support the findings below.", ParagraphStyle("SnapshotAssurance", parent=normal_style, fontSize=8.5, textColor=colors.HexColor("#0F172A"), spaceAfter=3)))
        flowables.append(Paragraph("Highlights below are drawn from cited medical records.", ParagraphStyle("SnapshotMeta", parent=normal_style, fontSize=8.5, textColor=colors.HexColor("#475569"), spaceAfter=4)))
    settlement_driver_rows: list[Paragraph] = []
    snapshot_promoted_semantic_families: set[str] = set()
    bullet_style = ParagraphStyle("SnapshotBullet", parent=normal_style, leftIndent=12, bulletIndent=0, spaceAfter=2)
    seen_snapshot_pain_scores: set[str] = set()

    def _event_verbatim_quote(evt: Event, pattern: str) -> str:
        texts: list[str] = []
        for fact in list(getattr(evt, "facts", []) or []) + list(getattr(evt, "exam_findings", []) or []) + list(getattr(evt, "diagnoses", []) or []):
            txt = _clean_line(getattr(fact, "text", "") or "")
            if txt:
                texts.append(txt)
        for txt in texts:
            if re.search(pattern, txt, re.I):
                q = re.sub(r"\s+", " ", txt).strip().strip("\"")
                if len(q.split()) >= 6:
                    return q
        return ""

    # Early care / ER on DOI
    first_er = next((e for e in dated_events if str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))) in {"er_visit", "hospital_admission", "hospital_discharge", "inpatient_daily_note"}), None)
    ed_mechanism_quote_present = False
    if first_er:
        a = chron_anchor(str(first_er.event_id))
        manifest.add_chron_anchor(a)
        cite_text = _event_or_entry_citation_text(first_er, a)
        settlement_driver_rows.append(Paragraph(
            f'<a name="{escape(a)}"/>- Early care documented: {escape(_event_date_label(first_er))} acute/initial treatment encounter. <font size="8">{escape(cite_text)}</font>',
            bullet_style
        ))
        mech_quote = _event_verbatim_quote(first_er, r"\b(motor vehicle|mvc|mva|rear[- ]end|collision|auto accident|car accident)\b")
        deny_quote = _event_verbatim_quote(first_er, r"\b(denies?|no prior|without prior|prior complaints?)\b")
        if mech_quote:
            ed_mechanism_quote_present = True
            settlement_driver_rows.append(Paragraph(
                f'- ED mechanism quote: "{escape(mech_quote)}"',
                bullet_style,
            ))
        if deny_quote:
            settlement_driver_rows.append(Paragraph(
                f'- Prior-condition quote: "{escape(deny_quote)}"',
                bullet_style,
            ))

    if first_er and not ed_mechanism_quote_present:
        ext.setdefault("sprint4d_invariants", {})
        ext["sprint4d_invariants"]["VERBATIM_REQUIRED_MISSING"] = True

    rm_mech = rm.get("mechanism") if isinstance(rm, dict) else {}
    if (
        isinstance(rm_mech, dict)
        and _clean_line(rm_mech.get("value"))
        and (rm_mech.get("citation_ids") or [])
        and (mechanism_alignment_status in {None, "PASS"})
        and not _mechanism_blocked_in_alignment(cca)
    ):
        refs = _refs_from_citation_ids([str(c) for c in (rm_mech.get("citation_ids") or [])], citation_by_id)
        if refs:
            a = chron_anchor("mechanism")
            manifest.add_chron_anchor(a)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
            settlement_driver_rows.append(Paragraph(
                f'<a name="{escape(a)}"/>- Mechanism documented: {escape(_clean_line(rm_mech.get("value")))}. <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            ))

    # Pain trajectory synthesis (citation-backed), avoids repetitive single-score bullets.
    early_pain_evt = None
    later_pain_evt = None
    early_pain = None
    later_pain = None
    for evt in dated_events:
        evt_blob = " ".join([str(getattr(f, "text", "") or "") for f in (getattr(evt, "facts", []) or [])])
        score = _pain_score(evt_blob)
        if score and early_pain is None:
            early_pain = score
            early_pain_evt = evt
        if score:
            later_pain = score
            later_pain_evt = evt
    if early_pain and later_pain and early_pain_evt and later_pain_evt:
        early_refs = event_citations_by_event.get(str(early_pain_evt.event_id), [])
        later_refs = event_citations_by_event.get(str(later_pain_evt.event_id), [])
        merged_refs = (early_refs + later_refs)[:8]
        if merged_refs:
            a = chron_anchor("pain_trajectory")
            manifest.add_chron_anchor(a)
            _links, cite_text = _citation_links_and_text(merged_refs, row_anchor=a, manifest=manifest)
            settlement_driver_rows.append(Paragraph(
                f'<a name="{escape(a)}"/>- Pain was recorded at {escape(early_pain)} in early care and remained {escape(later_pain)} in later documented treatment/discharge records. <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            ))
            seen_snapshot_pain_scores.add(early_pain)
            seen_snapshot_pain_scores.add(later_pain)

    # Continuous care if no gaps — Tweak 5: single source of truth from missing_records.gaps
    mr_payload = missing_records_payload or ext.get("missing_records") or {}
    global_gaps = [g for g in (mr_payload.get("gaps") or []) if str(g.get("rule_name") or "") == "global_gap" and int(g.get("gap_days") or 0) > 45]
    gap_anchor_meta = build_gap_anchor_metadata_rows(mr_payload, all_citations, page_map)
    raw_gaps_gt45 = [g for g in (gaps or []) if int(getattr(g, "duration_days", 0) or 0) > 45]
    lsv1_gap_gt45, lsv1_max_gap_days = _litigation_gap_summary(lsv1)
    # Unified gap truth: use missing_records.gaps directly (same source as Appendix C)
    mr_all_gaps = [g for g in (mr_payload.get("gaps") or []) if int(g.get("gap_days") or 0) > 0]
    if not mr_all_gaps:
        # cite first and last dated events if available
        if dated_events:
            start_evt = dated_events[0]
            end_evt = dated_events[-1]
            a = chron_anchor(f"continuity_{start_evt.event_id}")
            manifest.add_chron_anchor(a)
            refs = (event_citations_by_event.get(str(start_evt.event_id), []) + event_citations_by_event.get(str(end_evt.event_id), []))[:6]
            _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
            settlement_driver_rows.append(Paragraph(
                f'<a name="{escape(a)}"/>- Continuous care signal: no computed global treatment gaps >45 days in cited encounter chronology. <font size="8">{escape(cite_text)}</font>',
                bullet_style
            ))

    # Promoted findings from renderer manifest (pipeline-ranked, citation-backed)
    promoted_items = _manifest_promoted_items(rm)
    promoted_by_cat = _manifest_promoted_by_category(rm)
    blocked_or_review_label_texts = [
        _clean_line(str(it.get("label") or ""))
        for it in promoted_items
        if str(it.get("alignment_status") or "").strip().upper() not in {"", "PASS"}
    ]
    blocked_or_review_labels = {
        _dedupe_key(lbl)
        for lbl in blocked_or_review_label_texts
        if lbl
    }

    def _contains_blocked_snapshot_label(text: str | None) -> bool:
        candidate_norm = _dedupe_key(text or "")
        if not candidate_norm:
            return False
        for blocked in blocked_or_review_label_texts:
            blocked_norm = _dedupe_key(blocked)
            if blocked_norm and blocked_norm in candidate_norm:
                return True
        return False
    promoted_page1_considered = 0
    promoted_page1_rendered = 0
    snapshot_bucket_counts: dict[str, int] = {}
    settlement_seen_labels: set[str] = set()
    additional_findings_rows: list[Paragraph] = []
    additional_seen_labels: set[str] = set()
    def _queue_additional_finding(cat_key: str, label_text: str) -> None:
        label_dedupe_local = _dedupe_key(label_text)
        if label_dedupe_local and not _near_duplicate_seen(label_dedupe_local, additional_seen_labels):
            pretty = cat_key.replace("_", " ").title()
            additional_findings_rows.append(Paragraph(
                f"- {escape(pretty)}: {escape(label_text)}",
                bullet_style,
            ))
            additional_seen_labels.add(label_dedupe_local)

    snapshot_promoted_limit = 6
    for item in promoted_items:
        if promoted_page1_rendered >= snapshot_promoted_limit:
            break
        cat = str(item.get("category") or "unknown")
        promoted_page1_considered += 1
        if not item.get("headline_eligible", True):
            logger.info("page1 promoted finding omitted: reason=filtered category=%s label=%s", cat, _clean_line(item.get("label")))
            continue
        alignment_status = str(item.get("alignment_status") or "").strip().upper()
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
        if _dedupe_key(label) in blocked_or_review_labels:
            _queue_additional_finding(cat, label)
            logger.info("page1 promoted finding omitted: reason=blocked_or_review_label category=%s label=%s", cat, label)
            continue
        if _is_weak_facility_pain_label(label):
            logger.info("page1 promoted finding omitted: reason=weak_facility_pain_label category=%s label=%s", cat, label)
            continue
        if _is_financial_amount_label(label):
            logger.info("page1 promoted finding omitted: reason=financial_amount_label category=%s label=%s", cat, label)
            continue
        pain_sig = _pain_score(label)
        if pain_sig and pain_sig in seen_snapshot_pain_scores:
            logger.info("page1 promoted finding omitted: reason=duplicate_pain_signal category=%s label=%s", cat, label)
            continue
        if _is_pt_aggregate_count_label(label):
            logger.info("page1 promoted finding omitted: reason=pt_aggregate_count category=%s", cat)
            continue
        label_dedupe = _dedupe_key(label)
        if alignment_status != "PASS":
            _queue_additional_finding(cat, label)
            logger.info(
                "page1 promoted finding omitted: reason=alignment_not_pass category=%s status=%s label=%s",
                cat,
                alignment_status or "MISSING",
                label,
            )
            continue
        if _near_duplicate_seen(label_dedupe, settlement_seen_labels):
            logger.info("page1 promoted finding omitted: reason=duplicate category=%s label=%s", cat, label)
            continue
        pretty_cat = cat.replace("_", " ").title()
        rendered_label = _quote_if_verbatim(label, bool(item.get("is_verbatim")))
        settlement_driver_rows.append(Paragraph(
            f'<a name="{escape(row_anchor)}"/>- {escape(pretty_cat + ": " + rendered_label)} <font size="8">{escape(cite_text)}</font>',
            bullet_style,
        ))
        snapshot_bucket_counts[cat] = int(snapshot_bucket_counts.get(cat, 0) or 0) + 1
        settlement_seen_labels.add(label_dedupe)
        if pain_sig:
            seen_snapshot_pain_scores.add(pain_sig)
        fam = _manifest_semantic_family(item)
        if fam:
            snapshot_promoted_semantic_families.add(fam)
        promoted_page1_rendered += 1
    # Additional findings section should include any headline-eligible promoted finding
    # with alignment review/block status, even if its category is not part of the
    # snapshot highlights loop (e.g., visit_count).
    for cat, items in promoted_by_cat.items():
        for item in items:
            if not bool(item.get("headline_eligible", True)):
                continue
            alignment_status = str(item.get("alignment_status") or "").strip().upper()
            if alignment_status in {"", "PASS"}:
                continue
            label = _guardrail_text(_clean_line(item.get("label")), supported_injury=supported_injury)
            if not label:
                continue
            _queue_additional_finding(cat, label)
    if promoted_page1_considered and promoted_page1_rendered == 0:
        fallback_rendered = False
        for item in promoted_items:
            if not bool(item.get("headline_eligible", True)):
                continue
            alignment_status = str(item.get("alignment_status") or "").strip().upper()
            if alignment_status not in {"", "PASS"}:
                continue
            assertion = _guardrail_text(_clean_line(item.get("label")), supported_injury=supported_injury)
            if not assertion:
                continue
            if _is_pt_aggregate_count_label(assertion):
                continue
            if _is_financial_amount_label(assertion):
                continue
            pain_sig = _pain_score(assertion)
            if pain_sig and pain_sig in seen_snapshot_pain_scores:
                continue
            if _dedupe_key(assertion) in blocked_or_review_labels or _contains_blocked_snapshot_label(assertion):
                continue
            raw_cits = [str(c) for c in (item.get("citation_ids") or [])]
            refs = _refs_from_citation_ids(raw_cits, citation_by_id)
            if not refs and raw_cits:
                refs = _claim_row_citation_refs({"citations": raw_cits}, citations_by_page, single_doc_id)
            if not refs:
                continue
            row_anchor = chron_anchor(str(item.get("source_event_id") or "page1_promoted_fallback"))
            manifest.add_chron_anchor(row_anchor)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
            rendered_label = _quote_if_verbatim(assertion, bool(item.get("is_verbatim")))
            settlement_driver_rows.append(Paragraph(
                f'<a name="{escape(row_anchor)}"/>- Cited finding: {escape(rendered_label)} <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            ))
            if pain_sig:
                seen_snapshot_pain_scores.add(pain_sig)
            cat = str(item.get("category") or "unknown")
            snapshot_bucket_counts[cat] = int(snapshot_bucket_counts.get(cat, 0) or 0) + 1
            promoted_page1_rendered += 1
            fallback_rendered = True
            break
        ext.setdefault("sprint4d_invariants", {})
        ext["sprint4d_invariants"]["page1_promoted_considered"] = int(promoted_page1_considered)
        ext["sprint4d_invariants"]["page1_promoted_rendered"] = int(promoted_page1_rendered)
        ext["sprint4d_invariants"]["page1_promoted_fallback_used"] = bool(fallback_rendered)
        if not fallback_rendered:
            ext["sprint4d_invariants"]["PAGE1_PROMOTED_PARITY_FAILURE"] = True
            logger.warning("page1 promoted findings parity issue: considered=%s rendered=%s", promoted_page1_considered, promoted_page1_rendered)
    # Deterministic snapshot density controller:
    # backfill with citation-anchored promoted findings when snapshot is thin.
    bucket_minimums = {
        "imaging": 1 if promoted_by_cat.get("imaging") else 0,
        "diagnosis": 1 if promoted_by_cat.get("diagnosis") else 0,
        "procedure": 1 if promoted_by_cat.get("procedure") else 0,
        "objective_deficit": 1 if promoted_by_cat.get("objective_deficit") else 0,
        "symptom": 1 if promoted_by_cat.get("symptom") else 0,
    }

    def _add_density_backfill_item(item: dict[str, Any], cat: str) -> bool:
        assertion = _guardrail_text(_clean_line(item.get("label")), supported_injury=supported_injury)
        if not assertion or _is_pt_aggregate_count_label(assertion):
            return False
        if _is_weak_facility_pain_label(assertion):
            return False
        if _is_financial_amount_label(assertion):
            return False
        if _dedupe_key(assertion) in blocked_or_review_labels:
            return False
        pain_sig = _pain_score(assertion)
        if pain_sig and pain_sig in seen_snapshot_pain_scores:
            return False
        label_dedupe = _dedupe_key(assertion)
        if _near_duplicate_seen(label_dedupe, settlement_seen_labels):
            return False
        alignment_status = str(item.get("alignment_status") or "").strip().upper()
        if alignment_status not in {"", "PASS"}:
            return False
        raw_cits = [str(c) for c in (item.get("citation_ids") or [])]
        refs = _refs_from_citation_ids(raw_cits, citation_by_id)
        if not refs and raw_cits:
            refs = _claim_row_citation_refs({"citations": raw_cits}, citations_by_page, single_doc_id)
        if not refs:
            return False
        row_anchor = chron_anchor(str(item.get("source_event_id") or f"density_{cat}_{len(settlement_driver_rows)}"))
        manifest.add_chron_anchor(row_anchor)
        _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
        rendered_label = _quote_if_verbatim(assertion, bool(item.get("is_verbatim")))
        pretty_cat = cat.replace("_", " ").title()
        settlement_driver_rows.append(
            Paragraph(
                f'<a name="{escape(row_anchor)}"/>- {escape(pretty_cat + ": " + rendered_label)} <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            )
        )
        settlement_seen_labels.add(label_dedupe)
        if pain_sig:
            seen_snapshot_pain_scores.add(pain_sig)
        snapshot_bucket_counts[cat] = int(snapshot_bucket_counts.get(cat, 0) or 0) + 1
        return True

    for cat in ("imaging", "diagnosis", "procedure", "objective_deficit", "symptom"):
        target = int(bucket_minimums.get(cat) or 0)
        while int(snapshot_bucket_counts.get(cat) or 0) < target:
            candidates = list(promoted_by_cat.get(cat) or [])
            inserted = False
            for cand in candidates:
                if _add_density_backfill_item(cand, cat):
                    inserted = True
                    break
            if not inserted:
                break
    min_total_snapshot_rows = 6
    if len(settlement_driver_rows) < min_total_snapshot_rows:
        for cat in ("objective_deficit", "imaging", "diagnosis", "procedure", "symptom", "visit_count"):
            for cand in list(promoted_by_cat.get(cat) or []):
                if len(settlement_driver_rows) >= min_total_snapshot_rows:
                    break
                _add_density_backfill_item(cand, cat)
            if len(settlement_driver_rows) >= min_total_snapshot_rows:
                break
    # Snapshot is manifest-only for clinical claims to keep claim-context alignment filtering authoritative.
    claim_rows = list(ext.get("claim_rows") or [])

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
    pt_verified_allowed = _pt_verified_display_allowed(pt_payload) or (
        (not pt_payload.get("reported_vals"))
        and int(pt_payload.get("verified_count") or 0) == 0
        and int(pt_summary.get("visits") or 0) > 0
        and (
            str(pt_summary.get("count_source") or "").strip().lower() == "event_count"
            or int(pt_summary.get("event_count") or 0) > 0
        )
    )
    if pt_summary.get("visits") is not None and pt_verified_allowed:
        pt_display_label = "Verified"
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
            f'<a name="{escape(row_anchor)}"/>- Treatment intensity: PT visits ({escape(pt_display_label)}) {pt_summary["visits"]} encounters{duration_txt}. <font size="8">{escape(cite_text)}</font>',
            bullet_style,
        ))
        if pt_payload.get("reported_max") is not None and _pt_reported_numeric_allowed(pt_payload):
            rep_min = pt_payload.get("reported_min")
            rep_max = pt_payload.get("reported_max")
            rep_label = str(rep_max) if rep_min == rep_max else f"{rep_min}-{rep_max}"
            settlement_driver_rows.append(Paragraph(
                f"- PT visits (Reported in records): {escape(rep_label)} encounters.",
                bullet_style,
            ))
        elif pt_payload.get("reported_max") is not None:
            settlement_driver_rows.append(Paragraph(
                f"- {escape(_pt_unverified_disclosure_line(pt_payload))}",
                bullet_style,
            ))
        if isinstance(rm_pt, dict) and _clean_line(rm_pt.get("reconciliation_note")):
            recon_note = _clean_line(rm_pt.get("reconciliation_note"))
            if _contains_blocked_snapshot_label(recon_note) or _is_pt_aggregate_count_label(recon_note):
                recon_note = "PT references appear in records; encounter-level verification details are listed in the treatment section."
            settlement_driver_rows.append(Paragraph(
                f"- PT count reconciliation: {escape(recon_note)}",
                bullet_style,
            ))
    elif (pt_summary.get("visits") is not None) or (pt_payload.get("verified_count") or 0) > 0:
        if pt_payload.get("reported_max") is not None:
            settlement_driver_rows.append(Paragraph(
                f"- {escape(_pt_unverified_disclosure_line(pt_payload))}",
                bullet_style,
            ))
        settlement_driver_rows.append(Paragraph(
            "- No primary PT encounters were identified in the record; verified PT count is limited.",
            bullet_style,
        ))

    snapshot_warnings: list[str] = []
    if mechanism_display == "Injury mechanism is not expressly documented in chart notes.":
        snapshot_warnings.append("Injury mechanism is not expressly documented in chart notes.")
    has_img = bool(promoted_by_cat.get("imaging"))
    has_dx = bool(promoted_by_cat.get("diagnosis"))
    if not has_img:
        snapshot_warnings.append("Imaging detail is limited in this summary.")
    if not has_dx:
        snapshot_warnings.append("Diagnosis detail is limited in this summary.")
    if isinstance(rm, dict) and str(rm.get("billing_completeness") or "") == "partial":
        snapshot_warnings.append("Billing detail is incomplete in the provided packet; totals are partial.")
    # Tweak 1/5: In MEDIATION mode, skip record limitations and settlement_driver_rows.
    # The exec summary was already emitted above; these would add noise.
    if export_mode_norm != "MEDIATION":
        if snapshot_warnings:
            warn_style = ParagraphStyle("SnapshotWarn", parent=normal_style, backColor=colors.HexColor("#FFF7ED"), borderColor=colors.HexColor("#FDBA74"), borderWidth=0.5, borderPadding=4, spaceAfter=6)
            flowables.append(Paragraph("<b>Coverage notes</b>: " + " ".join(snapshot_warnings), warn_style))

        if not settlement_driver_rows:
            settlement_driver_rows.append(Paragraph("- No fully citation-supported settlement drivers were available for front-page display.", bullet_style))
        flowables.extend(settlement_driver_rows[:12])
        if additional_findings_rows:
            flowables.append(Spacer(1, 0.06 * inch))
            flowables.append(Paragraph("Additional Findings (Context Not Fully Verified)", h2_style))
            flowables.extend(additional_findings_rows[:4])
        flowables.append(Spacer(1, 0.1 * inch))

    flowables.append(Paragraph("Top 10 Case-Driving Events", h2_style))
    flowables.append(Paragraph("Top Record Anchors (citation-backed)", ParagraphStyle("Top10AliasNote", parent=normal_style, fontSize=8.5, textColor=colors.HexColor("#475569"), spaceAfter=3)))
    top_anchor_rows: list[Paragraph] = []
    top_seen = set()
    top_anchor_seen_families: set[str] = set()
    top_anchor_limit = 10
    top10_manifest_only = True
    visit_count_max: int | None = None
    for item in promoted_by_cat.get("visit_count", []):
        m = re.search(r"\b(\d+)\s+encounters?\b", str(item.get("label") or ""), re.I)
        if m:
            n = int(m.group(1))
            visit_count_max = n if visit_count_max is None else max(visit_count_max, n)
    # If manifest-only mode is disabled, retain a deterministic, non-heuristic fallback order.
    anchor_cat_order = ("objective_deficit", "imaging", "diagnosis", "procedure", "visit_count", "symptom")
    if not top10_manifest_only:
        for cat in anchor_cat_order:
            for item in promoted_by_cat.get(cat, []):
                if len(top_anchor_rows) >= top_anchor_limit:
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
                rendered_assertion = _quote_if_verbatim(assertion, bool(item.get("is_verbatim")))
                inline_cites = _top10_inline_citation_suffix(refs)
                top_anchor_rows.append(Paragraph(
                    f'<a name="{escape(a)}"/>- {escape((inline_cites + " " if inline_cites else "") + rendered_assertion)} <font size="8">{escape(cite_text)}</font>',
                    bullet_style,
                ))
                if fam:
                    top_anchor_seen_families.add(fam)
    manifest_driver_ids = [str(x) for x in (rm.get("top_case_drivers") or [])] if isinstance(rm, dict) else []
    if manifest_driver_ids and len(top_anchor_rows) < top_anchor_limit:
        projection_entries_by_id = {str(e.event_id): e for e in projection.entries}
        for eid in manifest_driver_ids:
            if len(top_anchor_rows) >= top_anchor_limit:
                break
            refs = event_citations_by_event.get(eid, [])
            entry = projection_entries_by_id.get(eid)
            if not refs or not entry:
                continue
            fact_pairs = _entry_fact_flag_pairs(entry)
            facts = [f for f, _is_verbatim in fact_pairs]
            candidate_pairs = [(f, is_verbatim) for f, is_verbatim in fact_pairs if not _is_meta_language(f)]
            # INV-Q4 (Pass 045): Use page-anchored key finding selection instead of
            # blindly picking candidate_pairs[0] — prevents wrong-date snippet bug.
            if candidate_pairs:
                key_finding_raw, key_is_verbatim = _pick_key_finding_page_anchored(
                    candidate_pairs, refs, citation_by_id
                )
            elif fact_pairs:
                key_finding_raw, key_is_verbatim = fact_pairs[0]
            else:
                key_finding_raw, key_is_verbatim = "", False
            key_finding = _guardrail_text(_clean_line(key_finding_raw), supported_injury=supported_injury)
            dedupe = _dedupe_key(key_finding)
            if not key_finding or _is_pt_aggregate_count_label(key_finding) or _near_duplicate_seen(dedupe, top_seen):
                continue
            top_seen.add(dedupe)
            a = chron_anchor(str(eid))
            manifest.add_chron_anchor(a)
            _links, cite_text = _citation_links_and_text(refs, row_anchor=a, manifest=manifest)
            pretty_date = _attorney_date_display(getattr(entry, "date_display", ""))
            date_prefix = f"{pretty_date}: " if pretty_date and pretty_date not in {"Undated", "Date not documented", ATTORNEY_UNDATED_LABEL} and not is_sentinel_date(str(getattr(entry, "date_display", ""))) else ""
            rendered_key_finding = _quote_if_verbatim(key_finding, key_is_verbatim)
            inline_cites = _top10_inline_citation_suffix(refs)
            top_anchor_rows.append(Paragraph(
                f'<a name="{escape(a)}"/>- {escape((inline_cites + " " if inline_cites else "") + date_prefix + rendered_key_finding)} <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            ))
    if not top10_manifest_only:
        prioritized_claims = sorted(claim_rows, key=lambda r: (-(int(r.get("selection_score") or 0)), str(r.get("date") or "9999-99-99")))
        for row in prioritized_claims:
            if len(top_anchor_rows) >= top_anchor_limit:
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
            date_prefix = f"{row_date}: " if row_date and row_date not in {"Undated", "Date not documented", ATTORNEY_UNDATED_LABEL} and str(row.get("date") or "").lower() != "unknown" else ""
            is_verbatim = "VERBATIM" in {str(f).upper() for f in (row.get("flags") or [])}
            rendered_assertion = _quote_if_verbatim(assertion, is_verbatim)
            inline_cites = _top10_inline_citation_suffix(refs)
            top_anchor_rows.append(Paragraph(
                f'<a name="{escape(a)}"/>- {escape((inline_cites + " " if inline_cites else "") + date_prefix + rendered_assertion)} <font size="8">{escape(cite_text)}</font>',
                bullet_style,
            ))
    if not top_anchor_rows:
        top_anchor_rows.append(Paragraph("No citation-supported top anchors were available for promotion.", normal_style))
    flowables.extend(top_anchor_rows)
    flowables.append(Spacer(1, 0.08 * inch))

    # Attorney-readiness case-theory sections (citation-backed and derived from existing typed data).
    def _append_case_theory_section(title: str, body: str, refs: list[dict[str, Any]], anchor_key: str) -> None:
        if not body or not refs:
            return
        flowables.append(Paragraph(title, h2_style))
        row_anchor = chron_anchor(anchor_key)
        manifest.add_chron_anchor(row_anchor)
        _links, cite_text = _citation_links_and_text(refs[:6], row_anchor=row_anchor, manifest=manifest)
        flowables.append(Paragraph(
            f'<a name="{escape(row_anchor)}"/>- {escape(body)} <font size="8">{escape(cite_text)}</font>',
            bullet_style,
        ))
        flowables.append(Spacer(1, 0.04 * inch))

    liability_body = ""
    liability_refs: list[dict[str, Any]] = []
    mechanism_allowed_for_promotion = (
        mechanism_alignment_status in {None, "PASS"}
        and not _mechanism_blocked_in_alignment(cca)
    )
    if (
        mechanism_allowed_for_promotion
        and isinstance(rm_mech, dict)
        and _clean_line(rm_mech.get("value"))
        and (rm_mech.get("citation_ids") or [])
    ):
        liability_refs = _refs_from_citation_ids([str(c) for c in (rm_mech.get("citation_ids") or [])], citation_by_id)
        if liability_refs:
            liability_body = f"Incident/mechanism is documented in cited records: {_clean_line(rm_mech.get('value'))}."
    if not liability_refs and first_er:
        liability_refs = event_citations_by_event.get(str(first_er.event_id), [])[:6]
        if liability_refs:
            liability_body = f"Acute presentation is documented on {_event_date_label(first_er)} in initial treatment records."
    _append_case_theory_section("Liability Facts", liability_body, liability_refs, "liability_facts")

    causation_body = ""
    causation_refs: list[dict[str, Any]] = []
    for cat in ("imaging", "diagnosis", "procedure", "objective_deficit"):
        for item in promoted_by_cat.get(cat, []):
            assertion = _guardrail_text(_clean_line(item.get("label")), supported_injury=supported_injury)
            if not assertion:
                continue
            raw_cits = [str(c) for c in (item.get("citation_ids") or [])]
            refs = _refs_from_citation_ids(raw_cits, citation_by_id)
            if not refs and raw_cits:
                refs = _claim_row_citation_refs({"citations": raw_cits}, citations_by_page, single_doc_id)
            if refs:
                causation_refs = refs
                causation_body = f"Cited diagnostic and treatment records document causation progression: {assertion}"
                break
        if causation_refs:
            break
    _append_case_theory_section("Causation Chain", causation_body, causation_refs, "causation_chain")
    causation_synthesis_body = ""
    causation_synthesis_refs: list[dict[str, Any]] = []
    if first_er:
        er_refs = event_citations_by_event.get(str(first_er.event_id), [])[:4]
        if er_refs and causation_refs:
            causation_synthesis_refs = (er_refs + causation_refs)[:8]
            causation_synthesis_body = (
                "Emergency department records document acute injury presentation following the incident mechanism. "
                "Subsequent cited diagnostic and treatment records document persistent pathology and symptom course consistent with that mechanism."
            )
    _append_case_theory_section("Causation Synthesis", causation_synthesis_body, causation_synthesis_refs, "causation_synthesis")

    damages_body = ""
    damages_refs: list[dict[str, Any]] = []
    for cat in ("symptom", "visit_count", "objective_deficit"):
        for item in promoted_by_cat.get(cat, []):
            assertion = _guardrail_text(_clean_line(item.get("label")), supported_injury=supported_injury)
            if not assertion:
                continue
            raw_cits = [str(c) for c in (item.get("citation_ids") or [])]
            refs = _refs_from_citation_ids(raw_cits, citation_by_id)
            if not refs and raw_cits:
                refs = _claim_row_citation_refs({"citations": raw_cits}, citations_by_page, single_doc_id)
            if refs:
                damages_refs = refs
                damages_body = f"Symptoms, functional findings, and treatment progression document damages impact: {assertion}"
                break
        if damages_refs:
            break
    if not damages_refs and isinstance(rm_pt, dict) and (rm_pt.get("citation_ids") or []):
        damages_refs = _refs_from_citation_ids([str(c) for c in (rm_pt.get("citation_ids") or [])], citation_by_id)
        if damages_refs:
            damages_body = "Treatment progression and therapy utilization are documented in cited records."
    _append_case_theory_section("Damages Progression", damages_body, damages_refs, "damages_progression")

    # Demand-ready synthesis section assembled from existing citation-backed sections.
    impact_parts: list[tuple[str, list[dict[str, Any]], str]] = []
    if liability_body and liability_refs:
        impact_parts.append((liability_body, liability_refs, "impact_summary_liability"))
    if causation_body and causation_refs:
        impact_parts.append((causation_body, causation_refs, "impact_summary_causation"))
    if damages_body and damages_refs:
        impact_parts.append((damages_body, damages_refs, "impact_summary_damages"))
    if impact_parts:
        flowables.append(Paragraph("Impact Summary (Demand-Ready)", h2_style))
        for body, refs, anchor_key in impact_parts[:3]:
            row_anchor = chron_anchor(anchor_key)
            manifest.add_chron_anchor(row_anchor)
            _links, cite_text = _citation_links_and_text(refs[:6], row_anchor=row_anchor, manifest=manifest)
            flowables.append(Paragraph(
                f'<a name="{escape(row_anchor)}"/>{escape(body)} <font size="8">{escape(cite_text)}</font>',
                normal_style,
            ))
        flowables.append(Spacer(1, 0.06 * inch))

    if export_mode_norm == "MEDIATION":
        # Pass31: Mediation Leverage Brief — deterministic section page in enforced order.
        # Sections 1-7 rendered here; Section 8 (Chronology) is the existing timeline page.
        flowables.append(PageBreak())
        flowables.append(Paragraph("MEDIATION LEVERAGE BRIEF", h1_style))
        flowables.append(Paragraph(
            "Sections below are deterministically generated from citation-anchored pipeline output. "
            "No valuation model data is included.",
            ParagraphStyle(
                "MediationBriefMeta",
                parent=normal_style,
                fontSize=8.5,
                textColor=colors.HexColor("#475569"),
                spaceAfter=6,
            ),
        ))

        # Pass 39 (D5 fix): Renderer is display-only. leverage_index_result must be
        # pre-computed by orchestrator.py and injected into ext before rendering.
        # No inline compute. No fallback. If not present, build_mediation_sections
        # renders the leverage section as "unavailable" — which is the correct signal
        # that the orchestrator did not run. Silent fallback is forbidden (govpreplan §10).
        _med_sections = build_mediation_sections(
            ext=ext,
            rm=rm,
            raw_events=raw_events,
            event_citations_by_event=event_citations_by_event,
            citation_by_id=citation_by_id,
            specials_summary=specials_summary,
            gaps=gaps,
        )
        _med_gate_fails = run_mediation_structural_gate(_med_sections)
        if _med_gate_fails:
            ext.setdefault("mediation_gate", {})
            ext["mediation_gate"]["fail_codes"] = _med_gate_fails

        for _msec in _med_sections:
            if not _msec.items:
                continue
            flowables.append(Paragraph(_msec.title, h2_style))
            for _mitem in _msec.items:
                if _mitem.support:
                    flowables.append(Paragraph(
                        f'- {escape(_mitem.label)} <font size="8">{escape(_mitem.support)}</font>',
                        bullet_style,
                    ))
                else:
                    flowables.append(Paragraph(f"- {escape(_mitem.label)}", bullet_style))
            flowables.append(Spacer(1, 0.08 * inch))
    else:
        # Case Severity Index (prepared upstream; renderer only formats).
        csi = ext.get("case_severity_index") if isinstance(ext.get("case_severity_index"), dict) else {}
        if csi:
            flowables.append(Paragraph("CASE SEVERITY INDEX", h2_style))
            base_csi = csi.get("base_csi", csi.get("case_severity_index"))
            band = _clean_line(csi.get("band"))
            risk_csi = csi.get("risk_adjusted_csi")
            profile = _clean_line(csi.get("profile"))
            comp = csi.get("component_scores") if isinstance(csi.get("component_scores"), dict) else {}
            obj_label = _clean_line(((comp.get("objective") or {}).get("label")) if isinstance(comp.get("objective"), dict) else "")
            int_label = _clean_line(((comp.get("intensity") or {}).get("label")) if isinstance(comp.get("intensity"), dict) else "")
            dur_label = _clean_line(((comp.get("duration") or {}).get("label")) if isinstance(comp.get("duration"), dict) else "")
            page_refs = []
            support = csi.get("support") if isinstance(csi.get("support"), dict) else {}
            if isinstance(support.get("page_refs"), list):
                page_refs = [r for r in support.get("page_refs") if isinstance(r, dict)]
            page_nums = sorted({int(r.get("page_number") or 0) for r in page_refs if int(r.get("page_number") or 0) > 0})
            support_txt = f"Citation(s): {' '.join(f'[p. {p}]' for p in page_nums[:8])}" if page_nums else ""
            csi_rows = []
            if base_csi is not None:
                csi_line = f"Case Severity Index: {base_csi}/10"
                if band:
                    csi_line += f" ({band})"
                if support_txt:
                    csi_line += f" {support_txt}"
                csi_rows.append(Paragraph(f"- {escape(csi_line)}", bullet_style))
            if risk_csi is not None and risk_csi != base_csi:
                csi_rows.append(Paragraph(f"- Risk-adjusted CSI: {escape(str(risk_csi))}/10", bullet_style))
            if obj_label:
                csi_rows.append(Paragraph(f"- Objective findings: {escape(obj_label)}", bullet_style))
            if int_label:
                csi_rows.append(Paragraph(f"- Treatment intensity: {escape(int_label)}", bullet_style))
            if dur_label:
                csi_rows.append(Paragraph(f"- Duration: {escape(dur_label)}", bullet_style))
            if profile:
                csi_rows.append(Paragraph(f"- {escape(profile)}", bullet_style))
            flowables.extend(csi_rows[:7])
            flowables.append(Spacer(1, 0.06 * inch))

    if include_internal_review_sections:
        flowables.append(Paragraph("Appendix E: Issue Flags", h2_style))
        issue_flag_rows = build_defense_vulnerabilities(lsv1)
        if issue_flag_rows:
            for item in issue_flag_rows[:4]:
                title = _clean_line(item.get("display_title"))
                msg = _clean_line(item.get("attorney_message"))
                text = title if not msg else f"{title}: {msg}"
                if text:
                    flowables.append(Paragraph(f"- {escape(text)}", bullet_style))
        else:
            flowables.append(Paragraph("- No material issue flags detected in cited records.", bullet_style))
        flowables.append(Spacer(1, 0.1 * inch))

    # Page 2 - Timeline table
    flowables.append(PageBreak())
    flowables.append(Paragraph('<a name="chronology_section_header"/>Medical Timeline (Litigation Ready)', h1_style))
    required_bucket_event_ids: dict[str, set[str]] = {}
    required_bucket_pages: dict[str, set[int]] = {}
    if isinstance(rm, dict):
        for bucket, payload in (rm.get("bucket_evidence") or {}).items():
            if not isinstance(payload, dict):
                continue
            ids = {str(eid).strip() for eid in (payload.get("event_ids") or []) if str(eid).strip()}
            if ids:
                required_bucket_event_ids[str(bucket)] = ids
                pages: set[int] = set()
                for eid in ids:
                    for ref in (event_citations_by_event.get(str(eid)) or []):
                        try:
                            pnum = int(ref.get("local_page") or ref.get("page") or 0)
                        except Exception:
                            pnum = 0
                        if pnum > 0:
                            pages.add(pnum)
                required_bucket_pages[str(bucket)] = pages
    timeline_audit: dict[str, Any] = {}
    unresolved_invasive_rows: list[dict[str, Any]] = []
    flowables.extend(_build_timeline_table(
        projection,
        styles,
        manifest,
        event_citations_by_event,
        citations_by_page,
        single_doc_id,
        required_bucket_event_ids=required_bucket_event_ids,
        required_bucket_pages=required_bucket_pages,
        timeline_audit=timeline_audit,
        unresolved_invasive_rows=unresolved_invasive_rows,
    ))
    missing_required_buckets = sorted(
        [b for b, ids in required_bucket_event_ids.items() if ids and b not in set(timeline_audit.get("rendered_buckets") or [])]
    )
    if missing_required_buckets:
        ext.setdefault("sprint4d_invariants", {})
        ext["sprint4d_invariants"]["missing_required_buckets"] = missing_required_buckets
        if "ed" in missing_required_buckets and required_bucket_event_ids.get("ed"):
            ext["sprint4d_invariants"]["ED_EXISTS_BUT_NOT_RENDERED"] = True
    if timeline_audit.get("dropped"):
        ext.setdefault("sprint4d_invariants", {})
        ext["sprint4d_invariants"]["timeline_drop_audit"] = timeline_audit
    if unresolved_invasive_rows:
        ext.setdefault("sprint4d_invariants", {})
        ext["sprint4d_invariants"]["unresolved_invasive_rows"] = [
            {
                "event_id": str(r.get("event_id") or ""),
                "event_type": str(r.get("event_type") or ""),
                "date_display": str(r.get("date_display") or ""),
                "provider_display": str(r.get("provider_display") or ""),
                "key_finding": str(r.get("key_finding") or ""),
                "refs": list(r.get("refs") or []),
            }
            for r in unresolved_invasive_rows
        ][:30]
        flowables.append(Spacer(1, 0.06 * inch))
        flowables.append(Paragraph("Procedures Requiring Date Clarification", h2_style))
        for idx, row in enumerate(unresolved_invasive_rows[:6]):
            refs = list(row.get("refs") or [])
            if refs:
                row_anchor = chron_anchor(f"unresolved_proc_{idx}_{row.get('event_id') or idx}")
                manifest.add_chron_anchor(row_anchor)
                _links, cite_text = _citation_links_and_text(refs, row_anchor=row_anchor, manifest=manifest)
                line = f'{row.get("event_type")}: {row.get("key_finding") or "Procedure documented without date anchor."}'
                flowables.append(Paragraph(f'<a name="{escape(row_anchor)}"/>- {escape(line)} <font size="8">{escape(cite_text)}</font>', normal_style))
            else:
                line = f'{row.get("event_type")}: {row.get("key_finding") or "Procedure documented without date anchor."}'
                flowables.append(Paragraph(f"- {escape(line)}", normal_style))

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
    if pt_summary.get("visits") is not None and pt_verified_allowed:
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
    elif pt_summary.get("visits") is not None or (pt_payload.get("verified_count") or 0) > 0:
        if pt_payload.get("reported_max") is not None:
            care_lines.append((_pt_unverified_disclosure_line(pt_payload), []))
        care_lines.append(("No primary PT encounters detected in record; verified PT count not displayed.", []))
    if pt_payload.get("reported_max") is not None and _pt_reported_numeric_allowed(pt_payload):
        rep_min = pt_payload.get("reported_min")
        rep_max = pt_payload.get("reported_max")
        rep_label = str(rep_max) if rep_min == rep_max else f"{rep_min}-{rep_max}"
        rep_refs: list[dict[str, Any]] = []
        for row in (pt_payload.get("reported") or [])[:6]:
            rep_refs.extend(_pt_ledger_refs(row, citation_by_id))
        care_lines.append((f"PT visits (Reported in records): {rep_label}", rep_refs[:8]))
        care_lines.append(("Reported totals are summaries; verified counts are enumerated dated encounters present in this packet.", []))
    elif pt_payload.get("reported_max") is not None:
        rep_refs: list[dict[str, Any]] = []
        for row in (pt_payload.get("reported") or [])[:6]:
            rep_refs.extend(_pt_ledger_refs(row, citation_by_id))
        care_lines.append((_pt_unverified_disclosure_line(pt_payload), rep_refs[:8]))
    if isinstance(rm_pt, dict) and _clean_line(rm_pt.get("reconciliation_note")):
        care_lines.append((f"PT count reconciliation: {_clean_line(rm_pt.get('reconciliation_note'))}", _refs_from_citation_ids([str(c) for c in (rm_pt.get('citation_ids') or [])], citation_by_id)))
    pt_date_anomaly = ((ext.get("pt_reconciliation") or {}).get("date_concentration_anomaly") or {}) if isinstance(ext.get("pt_reconciliation"), dict) else {}
    if isinstance(pt_date_anomaly, dict) and bool(pt_date_anomaly.get("triggered")):
        max_date = str(pt_date_anomaly.get("max_date") or "unknown date")
        max_count = int(pt_date_anomaly.get("max_date_count") or 0)
        total_pt = int(pt_payload.get("verified_count") or 0)
        care_lines.append((f"PT date concentration anomaly: {max_date} has {max_count} of {total_pt} verified PT encounters (review recommended).", []))
    gap_anchor_line, gap_anchor_refs = _gap_anchor_line(gap_anchor_meta, citation_by_id)
    if lsv1_gap_gt45 or global_gaps or raw_gaps_gt45:
        if gap_anchor_line and gap_anchor_refs:
            care_lines.append((gap_anchor_line, gap_anchor_refs))
        elif lsv1_gap_gt45:
            care_lines.append(("Treatment gap detected but citation boundary anchors were not identified (review required).", []))
        elif global_gaps or raw_gaps_gt45:
            care_lines.append(("Potential treatment gap identified but citation boundary anchors were not identified (review required).", []))
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
    if pt_payload.get("reported_max") is not None and _pt_reported_numeric_allowed(pt_payload):
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
        flowables.append(Paragraph("Not established from the provided packet.", normal_style))

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
        canvas.drawString(inch, 0.75 * inch, f"Medical Chronology: {display_matter_title}")
        if export_mode_norm == "MEDIATION":
            canvas.setFont("Helvetica", 7)
            canvas.drawString(inch, 0.58 * inch, "MEDIATION EXPORT (NO VALUATION MODEL)")
            canvas.drawString(
                inch,
                0.46 * inch,
                "Profile derived from documented treatment progression and objective findings only; no valuation modeling applied.",
            )
            canvas.setFont("Helvetica", 9)
        elif export_mode_norm == "INTERNAL":
            canvas.setFont("Helvetica", 7)
            canvas.drawString(inch, 0.58 * inch, "INTERNAL ANALYTICS — NOT FOR EXTERNAL DISTRIBUTION")
            canvas.setFont("Helvetica", 9)
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
    inv = ext.get("sprint4d_invariants") if isinstance(ext, dict) else None
    if isinstance(inv, dict) and bool(inv.get("ED_EXISTS_BUT_NOT_RENDERED")):
        raise RuntimeError("ED_EXISTS_BUT_NOT_RENDERED")
    _enforce_export_cleanroom(
        pdf_bytes,
        include_internal_review_sections=include_internal_review_sections,
        export_mode=export_mode_norm,
    )
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
