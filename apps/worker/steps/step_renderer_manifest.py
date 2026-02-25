"""
Build a pipeline-side RendererManifest for the chronology PDF renderer.

This step performs source selection / structuring only using already-computed pipeline outputs.
It does not run new extraction.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.shared.models import Event, RendererManifest, RendererDoiField, RendererCitationValue, RendererPtSummary, PromotedFinding


_SENTINEL_DATES = {"1900-01-01", "0001-01-01", "unknown", "undated", ""}

_CATEGORY_ORDER = {
    "objective_deficit": 0,
    "imaging": 1,
    "diagnosis": 2,
    "procedure": 3,
    "treatment": 4,
    "visit_count": 5,
    "symptom": 6,
}


def _iso_from_event(event: Event) -> tuple[str | None, str | None]:
    d = getattr(event, "date", None)
    if not d or not getattr(d, "value", None):
        return (None, None)
    v = d.value
    if isinstance(v, date):
        s = v.isoformat()
        if s in _SENTINEL_DATES:
            return (None, None)
        return (s, s)
    start = getattr(v, "start", None)
    end = getattr(v, "end", None)
    s = start.isoformat() if isinstance(start, date) else None
    e = end.isoformat() if isinstance(end, date) else None
    if s in _SENTINEL_DATES:
        s = None
    if e in _SENTINEL_DATES:
        e = None
    return (s, e or s)


def _collect_fact_text(event: Event) -> str:
    parts: list[str] = []
    for pool_name in ("facts", "diagnoses", "exam_findings", "procedures", "treatment_plan"):
        for fact in getattr(event, pool_name, []) or []:
            txt = str(getattr(fact, "text", "") or "").strip()
            if txt:
                parts.append(txt)
    return " ".join(parts)


def _build_doi(events: list[Event]) -> RendererDoiField:
    dated: list[tuple[str, Event]] = []
    for e in events:
        start, _end = _iso_from_event(e)
        if start and start not in _SENTINEL_DATES:
            dated.append((start, e))
    if not dated:
        return RendererDoiField(value=None, citation_ids=[], source="not_found")
    dated.sort(key=lambda x: x[0])
    doi, evt = dated[0]
    return RendererDoiField(value=doi, citation_ids=list(getattr(evt, "citation_ids", []) or []), source="inferred")


def _build_mechanism(events: list[Event]) -> RendererCitationValue:
    for e in events:
        blob = _collect_fact_text(e).lower()
        if not blob:
            continue
        if "rear-end" in blob or "rear end" in blob:
            return RendererCitationValue(value="rear-end motor vehicle collision", citation_ids=list(e.citation_ids or []))
        if "motor vehicle" in blob or " mva " in f" {blob} " or " mvc " in f" {blob} " or "collision" in blob:
            return RendererCitationValue(value="motor vehicle collision", citation_ids=list(e.citation_ids or []))
        if "fall" in blob:
            return RendererCitationValue(value="fall", citation_ids=list(e.citation_ids or []))
    return RendererCitationValue(value=None, citation_ids=[])


def _build_pt_summary(events: list[Event]) -> RendererPtSummary:
    pt_events = [e for e in events if str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))) == "pt_visit"]
    if not pt_events:
        return RendererPtSummary(count_source="not_found")

    count_from_snippet: int | None = None
    citations: list[str] = []
    starts: list[str] = []
    ends: list[str] = []
    discharge_status: str | None = None

    for e in pt_events:
        for cid in list(getattr(e, "citation_ids", []) or []):
            if cid not in citations:
                citations.append(cid)
        s, en = _iso_from_event(e)
        if s:
            starts.append(s)
        if en:
            ends.append(en)

        for fact in getattr(e, "facts", []) or []:
            txt = str(getattr(fact, "text", "") or "")
            m = re.search(r"\b(?:PT sessions documented|Aggregated PT sessions)\D+(\d+)\s+encounters?\b", txt, re.I)
            if m:
                count_from_snippet = max(count_from_snippet or 0, int(m.group(1)))
            elif (m2 := re.search(r"\bPT sessions documented:\s*(\d+)\b", txt, re.I)):
                count_from_snippet = max(count_from_snippet or 0, int(m2.group(1)))
            if "discharge" in txt.lower() and not discharge_status:
                discharge_status = txt[:180]

    if count_from_snippet is not None:
        total = count_from_snippet
        source = "aggregate_snippet"
    else:
        total = len(pt_events)
        source = "event_count"

    return RendererPtSummary(
        total_encounters=total,
        date_start=min(starts) if starts else None,
        date_end=max(ends) if ends else None,
        discharge_status=discharge_status,
        citation_ids=citations[:12],
        count_source=source,
    )


def _claim_to_category(claim_type: str) -> str:
    if claim_type == "IMAGING_FINDING":
        return "imaging"
    if claim_type == "INJURY_DX":
        return "diagnosis"
    if claim_type == "PROCEDURE":
        return "procedure"
    if claim_type == "TREATMENT_VISIT":
        return "treatment"
    if claim_type == "SYMPTOM":
        return "symptom"
    return "symptom"


def _claim_to_polarity_and_headline(assertion: str, flags: list[str], category: str) -> tuple[str | None, bool]:
    flags_l = {str(f).lower() for f in (flags or [])}
    a = (assertion or "").lower()
    negative = bool(
        ("degenerative_language" in flags_l)
        or "no acute" in a
        or "unremarkable" in a
        or "no fracture" in a
        or "no dislocation" in a
    )
    if negative:
        return ("negative", False)
    if category in {"objective_deficit", "imaging", "diagnosis", "procedure"}:
        return ("positive", True)
    return ("neutral", True)


def _promoted_findings_from_claim_rows(claim_rows: list[dict[str, Any]]) -> list[PromotedFinding]:
    out: list[PromotedFinding] = []
    seen_keys: set[str] = set()
    for row in claim_rows or []:
        citations = [str(c) for c in (row.get("citations") or []) if str(c).strip()]
        if not citations:
            continue
        assertion = str(row.get("assertion") or "").strip()
        if not assertion:
            continue
        claim_type = str(row.get("claim_type") or "")
        category = _claim_to_category(claim_type)
        # Promote clear objective deficits separately when claim rows call them dx/symptom.
        if re.search(r"\b(?:4/5|weakness|strength|range of motion|rom)\b", assertion, re.I):
            category = "objective_deficit"
        if re.search(r"\bvisits?\b|\bencounters?\b", assertion, re.I):
            category = "visit_count"
        polarity, headline = _claim_to_polarity_and_headline(assertion, list(row.get("flags") or []), category)
        key = f"{category}|{assertion.lower()}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        support_score = row.get("support_score")
        selection_score = row.get("selection_score")
        conf = 0.0
        if isinstance(selection_score, (int, float)):
            conf = max(conf, min(1.0, float(selection_score) / 100.0))
        if isinstance(support_score, (int, float)):
            conf = max(conf, min(1.0, float(support_score) / 5.0))
        severity = "high" if category in {"objective_deficit", "imaging", "diagnosis", "procedure"} and headline else ("low" if not headline else "medium")
        out.append(PromotedFinding(
            category=category, label=assertion, body_region=(row.get("body_region") or None),
            severity=severity, headline_eligible=headline, finding_polarity=polarity,
            citation_ids=citations, confidence=conf, source_event_id=str(row.get("event_id") or "") or None
        ))

    out.sort(key=lambda f: (_CATEGORY_ORDER.get(f.category, 99), 0 if f.headline_eligible else 1, {"high": 0, "medium": 1, "low": 2}.get(f.severity or "low", 2), -f.confidence))
    return out


def _top_case_drivers_from_claim_rows(claim_rows: list[dict[str, Any]]) -> list[str]:
    ranked = sorted(
        [r for r in (claim_rows or []) if r.get("event_id") and (r.get("citations") or [])],
        key=lambda r: (-(int(r.get("selection_score") or 0)), -(int(r.get("support_score") or 0)), str(r.get("date") or "9999-99-99")),
    )
    out: list[str] = []
    seen: set[str] = set()
    for r in ranked:
        eid = str(r.get("event_id"))
        if eid in seen:
            continue
        seen.add(eid)
        out.append(eid)
        if len(out) >= 20:
            break
    return out


def _billing_completeness(specials_summary: dict | None) -> str:
    if not isinstance(specials_summary, dict):
        return "none"
    flags = {str(f) for f in (specials_summary.get("flags") or [])}
    if "NO_BILLING_DATA" in flags:
        return "none"
    if {"PARTIAL_BILLING_ONLY", "MISSING_EOB_DATA"} & flags:
        return "partial"
    if specials_summary.get("by_provider") or (specials_summary.get("totals") or {}).get("total_charges"):
        return "complete"
    return "none"


def build_renderer_manifest(
    *,
    events: list[Event],
    evidence_graph_extensions: dict[str, Any] | None,
    specials_summary: dict | None,
) -> RendererManifest:
    ext = evidence_graph_extensions or {}
    claim_rows = list(ext.get("claim_rows") or [])
    promoted = _promoted_findings_from_claim_rows(claim_rows)
    return RendererManifest(
        doi=_build_doi(events),
        mechanism=_build_mechanism(events),
        pt_summary=_build_pt_summary(events),
        promoted_findings=promoted,
        top_case_drivers=_top_case_drivers_from_claim_rows(claim_rows),
        billing_completeness=_billing_completeness(specials_summary),
    )

