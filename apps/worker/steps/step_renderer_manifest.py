"""
Build a pipeline-side RendererManifest for the chronology PDF renderer.

This step performs source selection / structuring only using already-computed pipeline outputs.
It does not run new extraction.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.shared.models import Citation, Event, RendererManifest, RendererDoiField, RendererCitationValue, RendererPtSummary, PromotedFinding


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

_GENERIC_PLACEHOLDER_PATTERNS = [
    re.compile(r"\b(?:impression|assessment|consultation)\s+(?:documented|reviewed|noted)\b", re.I),
    re.compile(r"\bfollow-?up and treatment planning noted\b", re.I),
]


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


def _event_text_blobs(event: Event) -> list[str]:
    blobs: list[str] = []
    for val in (getattr(event, "reason_for_visit", None), getattr(event, "chief_complaint", None)):
        txt = str(val or "").strip()
        if txt:
            blobs.append(txt)
    for pool_name in ("facts", "diagnoses", "exam_findings", "procedures", "treatment_plan"):
        for fact in getattr(event, pool_name, []) or []:
            txt = str(getattr(fact, "text", "") or "").strip()
            if txt and not getattr(fact, "technical_noise", False):
                blobs.append(txt)
    imaging = getattr(event, "imaging", None)
    for fact in getattr(imaging, "impression", []) or []:
        txt = str(getattr(fact, "text", "") or "").strip()
        if txt and not getattr(fact, "technical_noise", False):
            blobs.append(txt)
    return blobs


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
    patterns = [
        (re.compile(r"\b(rear[- ]end)\b", re.I), "rear-end motor vehicle collision"),
        (re.compile(r"\b(motor vehicle collision|motor vehicle accident|mvc|mva|auto accident|car accident)\b", re.I), "motor vehicle collision"),
        (re.compile(r"\b(slip and fall|trip and fall|fall)\b", re.I), "fall"),
        (re.compile(r"\b(pedestrian (?:struck|hit)|struck by vehicle)\b", re.I), "pedestrian struck"),
        (re.compile(r"\b(motorcycle|bike accident|bicycle accident)\b", re.I), "vehicle collision"),
        (re.compile(r"\b(work(?:place)? injury|on the job|lifting injury)\b", re.I), "work injury"),
    ]
    # Prefer earlier events because mechanism is usually documented near DOI.
    ordered = sorted(events, key=lambda e: (_iso_from_event(e)[0] or "9999-99-99", str(getattr(e, "event_id", ""))))
    for e in ordered:
        blob = " ".join(_event_text_blobs(e)).lower()
        if not blob:
            continue
        for pat, label in patterns:
            if pat.search(blob):
                cids = [str(c) for c in (getattr(e, "citation_ids", []) or []) if str(c).strip()]
                if cids:
                    return RendererCitationValue(value=label, citation_ids=cids[:8])
    return RendererCitationValue(value=None, citation_ids=[])


def _build_mechanism_from_citations(citations: list[Citation] | None) -> RendererCitationValue:
    if not citations:
        return RendererCitationValue(value=None, citation_ids=[])
    patterns = [
        (re.compile(r"\b(rear[- ]end)\b", re.I), "rear-end motor vehicle collision"),
        (re.compile(r"\b(motor vehicle collision|motor vehicle accident|mvc|mva|auto accident|car accident)\b", re.I), "motor vehicle collision"),
        (re.compile(r"\b(slip and fall|trip and fall|fall)\b", re.I), "fall"),
        (re.compile(r"\b(pedestrian (?:struck|hit)|struck by vehicle)\b", re.I), "pedestrian struck"),
        (re.compile(r"\b(work(?:place)? injury|on the job|lifting injury)\b", re.I), "work injury"),
    ]
    for c in sorted(citations, key=lambda x: int(getattr(x, "page_number", 999999) or 999999)):
        sn = str(getattr(c, "snippet", "") or "").strip()
        if not sn:
            continue
        low = sn.lower()
        for pat, label in patterns:
            if pat.search(low):
                return RendererCitationValue(value=label, citation_ids=[str(c.citation_id)])
    return RendererCitationValue(value=None, citation_ids=[])


def _build_pt_summary(events: list[Event], citations: list[Citation] | None = None) -> RendererPtSummary:
    pt_evidence_events: list[Event] = []
    for e in events:
        etype = str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", "")))
        blobs = _event_text_blobs(e)
        joined = " ".join(blobs).lower()
        if etype == "pt_visit" or ("physical therapy" in joined or re.search(r"\bpt\b", joined)):
            pt_evidence_events.append(e)
    if not pt_evidence_events:
        return RendererPtSummary(count_source="not_found")

    aggregate_counts: list[int] = []
    citation_ids_collected: list[str] = []
    starts: list[str] = []
    ends: list[str] = []
    discharge_status: str | None = None

    for e in pt_evidence_events:
        for cid in list(getattr(e, "citation_ids", []) or []):
            if cid not in citation_ids_collected:
                citation_ids_collected.append(cid)
        s, en = _iso_from_event(e)
        if s:
            starts.append(s)
        if en:
            ends.append(en)

        for txt in _event_text_blobs(e):
            m = re.search(r"\b(?:PT sessions documented|Aggregated PT sessions)\D+(\d+)\s+encounters?\b", txt, re.I)
            if m:
                aggregate_counts.append(int(m.group(1)))
            elif (m2 := re.search(r"\bPT sessions documented:\s*(\d+)\b", txt, re.I)):
                aggregate_counts.append(int(m2.group(1)))
            if "discharge" in txt.lower() and not discharge_status:
                discharge_status = txt[:180]

    # Citation-backed fallback for aggregate summaries that were not promoted into event facts.
    if citations:
        for c in citations:
            sn = str(getattr(c, "snippet", "") or "")
            low = sn.lower()
            if "physical therapy" not in low and "pt " not in f" {low} " and "pt sessions" not in low and "aggregated pt sessions" not in low:
                continue
            m = re.search(r"\b(?:PT sessions documented|Aggregated PT sessions)\D+(\d+)\s+encounters?\b", sn, re.I)
            if m:
                aggregate_counts.append(int(m.group(1)))

    if aggregate_counts:
        total = max(aggregate_counts)
        source = "aggregate_snippet"
    else:
        total = sum(1 for e in pt_evidence_events if str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))) == "pt_visit")
        total = total or len(pt_evidence_events)
        source = "event_count"
    unique_counts = sorted({c for c in aggregate_counts if c > 0})
    note = None
    cmin = min(unique_counts) if unique_counts else None
    cmax = max(unique_counts) if unique_counts else None
    if cmin is not None and cmax is not None and cmin != cmax:
        note = f"PT volume summaries vary across records ({cmin}-{cmax} encounters); displayed count uses the highest citation-backed aggregate."

    return RendererPtSummary(
        total_encounters=total,
        encounter_count_min=cmin,
        encounter_count_max=cmax,
        date_start=min(starts) if starts else None,
        date_end=max(ends) if ends else None,
        discharge_status=discharge_status,
        reconciliation_note=note,
        citation_ids=citation_ids_collected[:12],
        count_source=source,
    )


def _promoted_findings_from_citations(
    citations: list[Citation] | None,
    existing: list[PromotedFinding],
) -> list[PromotedFinding]:
    if not citations:
        return existing
    seen = {f"{pf.category}|{pf.label.strip().lower()}" for pf in existing}
    have_categories = {pf.category for pf in existing if pf.headline_eligible}
    out = list(existing)

    def add(category: str, label: str, citation_id: str, *, severity: str = "high", headline: bool = True, polarity: str | None = None):
        key = f"{category}|{label.strip().lower()}"
        if key in seen:
            return
        seen.add(key)
        out.append(PromotedFinding(
            category=category,
            label=label.strip(),
            severity=severity, headline_eligible=headline, finding_polarity=polarity,
            citation_ids=[citation_id],
            confidence=0.75 if headline else 0.55,
        ))

    # Only fallback-fill missing critical categories to avoid overfitting/duplication.
    need_dx = "diagnosis" not in have_categories
    need_obj = "objective_deficit" not in have_categories
    need_proc = "procedure" not in have_categories
    need_img = "imaging" not in have_categories

    for c in sorted(citations, key=lambda x: int(getattr(x, "page_number", 999999) or 999999)):
        sn = str(getattr(c, "snippet", "") or "").strip()
        if not sn:
            continue
        # Generic diagnosis fallback: ICD-coded diagnosis lines
        if need_dx and re.search(r"\bICD-10\b", sn, re.I):
            if re.search(r"\b([A-TV-Z]\d{1,2}(?:\.\d+)?)\b", sn):
                add("diagnosis", sn, str(c.citation_id), severity="high", headline=True, polarity="positive")
                continue
        # Generic procedure/intervention fallback
        if need_proc and re.search(r"\b(injection|epidural|surgery|operative|arthroscop|fusion|procedure performed)\b", sn, re.I):
            add("procedure", sn, str(c.citation_id), severity="high", headline=True, polarity="positive")
            continue
        # Generic objective-deficit fallback
        if need_obj and re.search(r"\b(weakness|strength|reflex|diminished|range of motion|rom|spasm|lordosis|[0-5]/5)\b", sn, re.I):
            # avoid pure headers/labels
            if not re.fullmatch(r"[A-Za-z0-9 /:+().-]{1,40}", sn.strip()):
                add("objective_deficit", sn, str(c.citation_id), severity="high", headline=True, polarity="positive")
                continue
        # Generic imaging pathology fallback (positive structural findings only)
        if need_img and re.search(r"\b(disc|foramen|foraminal|stenosis|herniat|protrusion|tear|edema|compression|fracture|displacement)\b", sn, re.I):
            negative = bool(re.search(r"\b(no acute|unremarkable|no fracture|normal)\b", sn, re.I))
            add("imaging", sn, str(c.citation_id), severity=("low" if negative else "high"), headline=(not negative), polarity=("negative" if negative else "positive"))
            continue

    out.sort(key=lambda f: (_CATEGORY_ORDER.get(f.category, 99), 0 if f.headline_eligible else 1, {"high": 0, "medium": 1, "low": 2}.get(f.severity or "low", 2), -f.confidence))
    return out


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


def _promoted_findings_from_events(events: list[Event], existing: list[PromotedFinding]) -> list[PromotedFinding]:
    seen = {f"{pf.category}|{pf.label.strip().lower()}" for pf in existing}
    out: list[PromotedFinding] = list(existing)
    for e in events:
        event_cids = [str(c) for c in (getattr(e, "citation_ids", []) or []) if str(c).strip()]
        if not event_cids:
            continue
        pools: list[tuple[str, list[Any], str | None]] = [
            ("diagnosis", list(getattr(e, "diagnoses", []) or []), None),
            ("objective_deficit", list(getattr(e, "exam_findings", []) or []), None),
            ("procedure", list(getattr(e, "procedures", []) or []), None),
            ("treatment", list(getattr(e, "treatment_plan", []) or []), None),
        ]
        imaging = getattr(e, "imaging", None)
        if imaging and getattr(imaging, "impression", None):
            body_part = str(getattr(imaging, "body_part", "") or "").strip() or None
            pools.append(("imaging", list(getattr(imaging, "impression", []) or []), body_part))
        for category, facts, body_region in pools:
            for fact in facts:
                txt = str(getattr(fact, "text", "") or "").strip()
                if not txt or getattr(fact, "technical_noise", False):
                    continue
                citation_ids = [str(c) for c in (getattr(fact, "citation_ids", []) or []) if str(c).strip()] or event_cids
                if not citation_ids:
                    continue
                # objective deficits are elevated by source field; generic pain-only exam items are not headline-worthy
                polarity, headline = _claim_to_polarity_and_headline(txt, list(getattr(e, "flags", []) or []), category)
                if category == "objective_deficit" and re.search(r"\bpain\b", txt, re.I) and not re.search(r"\b(weakness|strength|reflex|rom|lordosis|spasm|4/5)\b", txt, re.I):
                    headline = False
                key = f"{category}|{txt.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                severity = "high" if category in {"objective_deficit", "imaging", "diagnosis", "procedure"} and headline else ("low" if not headline else "medium")
                eid = str(getattr(e, "event_id", "") or "").strip() or None
                out.append(PromotedFinding(
                    category=category,
                    label=txt,
                    body_region=body_region,
                    severity=severity,
                    headline_eligible=headline,
                    finding_polarity=polarity,
                    citation_ids=citation_ids[:8],
                    confidence=min(1.0, float(getattr(e, "confidence", 0) or 0) / 100.0),
                    source_event_id=eid,
                ))
    out.sort(key=lambda f: (_CATEGORY_ORDER.get(f.category, 99), 0 if f.headline_eligible else 1, {"high": 0, "medium": 1, "low": 2}.get(f.severity or "low", 2), -f.confidence))
    return out


def _top_case_drivers_from_claim_rows(claim_rows: list[dict[str, Any]]) -> list[str]:
    def _row_rank(r: dict[str, Any]) -> tuple:
        ctype = str(r.get("claim_type") or "")
        cat = _claim_to_category(ctype)
        assertion = str(r.get("assertion") or "")
        if re.search(r"\b(?:4/5|weakness|strength|reflex|rom)\b", assertion, re.I):
            cat = "objective_deficit"
        pol, headline = _claim_to_polarity_and_headline(assertion, list(r.get("flags") or []), cat)
        generic = any(p.search(assertion) for p in _GENERIC_PLACEHOLDER_PATTERNS)
        return (
            _CATEGORY_ORDER.get(cat, 99),
            0 if headline else 1,
            1 if generic else 0,
            -(int(r.get("selection_score") or 0)),
            -(int(r.get("support_score") or 0)),
            str(r.get("date") or "9999-99-99"),
            1 if pol == "negative" else 0,
        )

    ranked = sorted(
        [
            r for r in (claim_rows or [])
            if r.get("event_id") and (r.get("citations") or []) and not any(p.search(str(r.get("assertion") or "")) for p in _GENERIC_PLACEHOLDER_PATTERNS)
        ],
        key=_row_rank,
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
    citations: list[Citation] | None = None,
) -> RendererManifest:
    ext = evidence_graph_extensions or {}
    claim_rows = list(ext.get("claim_rows") or [])
    promoted = _promoted_findings_from_claim_rows(claim_rows)
    promoted = _promoted_findings_from_events(events, promoted)
    promoted = _promoted_findings_from_citations(citations, promoted)
    mechanism = _build_mechanism(events)
    if not mechanism.value:
        mechanism = _build_mechanism_from_citations(citations)
    return RendererManifest(
        doi=_build_doi(events),
        mechanism=mechanism,
        pt_summary=_build_pt_summary(events, citations),
        promoted_findings=promoted,
        top_case_drivers=_top_case_drivers_from_claim_rows(claim_rows),
        billing_completeness=_billing_completeness(specials_summary),
    )
