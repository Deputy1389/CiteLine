"""
Moat section rendering for chronology PDF export.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from reportlab.platypus import Paragraph, Spacer
from reportlab.lib.units import inch

from apps.worker.steps.export_render.common import (
    _sanitize_render_sentence,
    _is_sdoh_noise,
    parse_date_string,
)
from apps.worker.quality.text_quality import clean_text, is_garbage


def _render_section_block(
    flowables: list,
    title: str,
    rows: list[str] | None,
    h2_style: Any,
    normal_style: Any,
    *,
    empty_text: str = "No findings for this category.",
    stats: dict | None = None,
    allow_fallback: bool = True,
) -> None:
    flowables.append(Paragraph(title, h2_style))
    if not rows:
        flowables.append(Paragraph(empty_text, normal_style))
        flowables.append(Spacer(1, 0.08 * inch))
        return
    rendered = 0
    for row in rows[:12]:
        line = _sanitize_render_sentence(clean_text(row))
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            if stats is not None:
                stats["top10_items_dropped_due_to_quality"] = stats.get("top10_items_dropped_due_to_quality", 0) + 1
            if allow_fallback:
                flowables.append(Paragraph("Content present but low-quality/duplicative; see cited source.", normal_style))
                rendered += 1
            continue
        flowables.append(Paragraph(f"- {line}", normal_style))
        rendered += 1
    if rendered == 0:
        flowables.append(Paragraph(empty_text, normal_style))
    flowables.append(Spacer(1, 0.08 * inch))


def _case_collapse_rows(ext: dict) -> list[str]:
    rows = []
    for item in (ext.get("case_collapse_candidates") or []):
        if not isinstance(item, dict):
            continue
        frag = str(item.get("fragility_type") or "").replace("_", " ").title()
        why = str(item.get("why") or item.get("title") or "").strip()
        score = item.get("fragility_score")
        score_txt = f" (Score {score})" if score is not None else ""
        if why:
            rows.append(f"{frag}{score_txt}: {why}")
        elif frag:
            rows.append(f"{frag}{score_txt}")
    return rows


def _causation_ladder_rows(ext: dict) -> list[str]:
    rows = []
    for item in (ext.get("causation_chains") or []):
        if isinstance(item, dict):
            summary = item.get("summary") or item.get("narrative") or ""
            if summary:
                rows.append(str(summary))
                continue
            steps = item.get("steps") or []
            if steps:
                rows.append(" > ".join(str(s) for s in steps if s))
        elif item:
            rows.append(str(item))
    return rows


def _contradiction_rows(ext: dict) -> list[str]:
    rows = []
    for item in (ext.get("contradiction_matrix") or []):
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").replace("_", " ").title()
        supporting = item.get("supporting") or {}
        contradicting = item.get("contradicting") or {}
        s_val = supporting.get("value") or ""
        c_val = contradicting.get("value") or ""
        s_date = supporting.get("date") or ""
        c_date = contradicting.get("date") or ""
        if s_val or c_val:
            rows.append(
                f"{category}: {s_val} ({s_date}) vs {c_val} ({c_date})"
            )
    return rows


def _narrative_duality_rows(ext: dict) -> list[str]:
    duality = ext.get("narrative_duality")
    if not isinstance(duality, dict):
        return []
    rows = []
    plaintiff = duality.get("plaintiff_narrative") or {}
    defense = duality.get("defense_narrative") or {}
    p_summary = plaintiff.get("summary") or ""
    d_summary = defense.get("summary") or ""
    if p_summary:
        rows.append(f"Plaintiff: {p_summary}")
    if d_summary:
        rows.append(f"Defense: {d_summary}")
    points = (plaintiff.get("points") or [])[:3]
    for p in points:
        if not isinstance(p, dict):
            continue
        rows.append(f"Plaintiff point: {p.get('assertion') or p.get('summary')}")
    points = (defense.get("points") or [])[:3]
    for d in points:
        if not isinstance(d, dict):
            continue
        rows.append(f"Defense point: {d.get('assertion') or d.get('summary')}")
    return [r for r in rows if r and str(r).strip()]


def _missing_record_rows(ext: dict, missing_records_payload: dict | None) -> list[str]:
    rows = []
    payload = missing_records_payload or ext.get("missing_records") or {}
    top_requests = list((payload.get("priority_requests_top3") or []))
    if top_requests:
        for req in top_requests[:3]:
            if not isinstance(req, dict):
                continue
            dfrom = str(((req.get("date_range") or {}).get("from") or "")).strip()
            dto = str(((req.get("date_range") or {}).get("to") or "")).strip()
            rows.append(
                f"#{req.get('rank', '?')} {req.get('provider_display_name', 'Any provider')} "
                f"| {dfrom} to {dto} | Priority: {req.get('priority_tier', 'Medium')}"
            )
    gaps = list((payload.get("gaps") or []))
    for gap in gaps[:4]:
        if not isinstance(gap, dict):
            continue
        rows.append(str(gap.get("summary") or gap.get("label") or gap))
    return rows


def _top10_rows(projection_entries: list, score_func: Any) -> list[str]:
    candidates = []
    for entry in projection_entries:
        blob = " ".join(entry.facts or []).lower()
        if "routine follow-up" in blob and "acetaminophen" in blob:
            continue
        if "routine continuity gap" in blob:
            continue
        if "difficult mission late kind" in blob:
            continue
        if "preferred language" in blob:
            continue
        if _is_sdoh_noise(blob):
            continue
        score = score_func(entry)
        label = (entry.event_type_display or "").lower()
        if "emergency" in label:
            score += 10
        if "imaging" in label:
            score += 10
        if "procedure" in label:
            score += 15
        candidates.append((score, entry))

    scored = sorted(candidates, key=lambda x: x[0], reverse=True)
    top10_entries = []
    seen_blobs = set()
    for _, entry in scored:
        blob = " ".join(entry.facts or []).lower().strip()
        clean_blob = re.sub(r"\W+", " ", blob)
        if clean_blob in seen_blobs:
            continue
        seen_blobs.add(clean_blob)
        top10_entries.append(entry)
        if len(top10_entries) >= 10:
            break

    top10_entries = sorted(
        top10_entries,
        key=lambda e: (parse_date_string(e.date_display) or date.min, e.event_id),
    )
    rows = []
    same_day_label_counts: dict[tuple[str, str], int] = {}
    for entry in top10_entries:
        evt_date = parse_date_string(entry.date_display)
        if not evt_date:
            continue
        facts_blob = _sanitize_render_sentence(" ".join(entry.facts or []))
        facts_blob = re.sub(r"\.\.+", ".", facts_blob)
        facts_blob = re.sub(r"\s{2,}", " ", facts_blob).strip()
        facts_blob = re.sub(r"\b(?:and|or|with|to)\.?\s*$", "", facts_blob, flags=re.IGNORECASE).strip()
        if not facts_blob:
            continue
        if not entry.citation_display:
            continue
        same_day_label = (evt_date.isoformat(), str(entry.event_type_display or "").strip().lower())
        if same_day_label_counts.get(same_day_label, 0) >= 2:
            continue
        same_day_label_counts[same_day_label] = same_day_label_counts.get(same_day_label, 0) + 1
        rows.append(f"{evt_date.isoformat()} | {entry.event_type_display} | {facts_blob}")
    return rows


def build_moat_section_flowables(
    projection_entries: list,
    evidence_graph_payload: dict | None,
    missing_records_payload: dict | None,
    styles: Any,
) -> tuple[list, dict]:
    ext = {}
    if evidence_graph_payload and isinstance(evidence_graph_payload, dict):
        ext = evidence_graph_payload.get("extensions", {}) or {}

    h2_style = styles["Heading2"]
    normal_style = styles["Normal"]
    flowables: list = []
    stats: dict = {}

    sections = [
        ("Case Collapse Candidates", _case_collapse_rows(ext)),
        ("Causation Ladder", _causation_ladder_rows(ext)),
        ("Contradiction Matrix", _contradiction_rows(ext)),
        ("Narrative Duality", _narrative_duality_rows(ext)),
    ]

    from apps.worker.steps.export_render.common import _projection_entry_substance_score
    top10_rows = _top10_rows(projection_entries, _projection_entry_substance_score)
    sections.append(("Case Driving Events", top10_rows))

    sections.append(("Missing Record Detection", _missing_record_rows(ext, missing_records_payload)))

    populated = 0
    for title, rows in sections:
        if rows and any(r.strip() for r in rows):
            populated += 1
    if populated == 0:
        flowables.append(Paragraph("Strategic Scan Result", h2_style))
        flowables.append(Paragraph("No strategic flags detected in this record set.", normal_style))
        flowables.append(Spacer(1, 0.12 * inch))
        return flowables, stats

    for title, rows in sections:
        if not rows or not any(r.strip() for r in rows):
            continue
        _render_section_block(
            flowables,
            title,
            rows,
            h2_style,
            normal_style,
            stats=stats,
            allow_fallback=(title != "Case Driving Events"),
        )

    return flowables, stats
