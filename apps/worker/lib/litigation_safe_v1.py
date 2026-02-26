from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.shared.models import Event, Gap

_REASON_MESSAGES = {
    "MECHANISM_OR_DIAGNOSIS_UNSUPPORTED": "Snapshot mechanism and/or diagnosis entries are not fully supported by cited extracted records.",
    "PROCEDURE_DATE_MISSING": "Imaging/procedure/injection/surgery events require a parseable date for lawyer-ready export.",
    "GAP_STATEMENT_INCONSISTENT": "Computed treatment-gap result conflicts with gap data used for export statements/appendix.",
    "BILLING_IMPLIED_COMPLETE": "Partial billing extraction would imply completeness without the required partial/incomplete disclosures.",
    "INTERNAL_CONTRADICTION": "Internal numeric/provider contradictions detected across export summary aggregates.",
}

_MECH_TERM_MAP = {
    "motor vehicle": {"motor vehicle", "mvc", "mva", "collision", "crash", "rear-end", "rear end"},
    "collision": {"collision", "crash", "mvc", "mva", "motor vehicle", "rear-end", "rear end"},
    "fall": {"fall", "fell", "slip", "trip"},
}


def build_litigation_safe_v1_snapshot(renderer_manifest: dict | None) -> dict[str, Any]:
    rm = renderer_manifest if isinstance(renderer_manifest, dict) else {}
    promoted = [x for x in (rm.get("promoted_findings") or []) if isinstance(x, dict)]
    diagnoses = [str(x.get("label") or "").strip() for x in promoted if str(x.get("category") or "") == "diagnosis" and str(x.get("label") or "").strip()]
    pt_summary = rm.get("pt_summary") if isinstance(rm.get("pt_summary"), dict) else {}
    return {
        "mechanism": str(((rm.get("mechanism") or {}).get("value")) or "").strip() if isinstance(rm.get("mechanism"), dict) else "",
        "mechanism_citation_ids": [str(c) for c in (((rm.get("mechanism") or {}).get("citation_ids")) or [])] if isinstance(rm.get("mechanism"), dict) else [],
        "diagnoses": diagnoses,
        "pt_total_encounters": pt_summary.get("total_encounters"),
        "pt_count_source": pt_summary.get("count_source"),
    }


def validateLitigationSafeV1(snapshot: dict | None, events: list[Event] | list[dict] | None, extractionContext: dict | None) -> dict[str, Any]:
    return validate_litigation_safe_v1(snapshot, events, extractionContext)


def validate_litigation_safe_v1(snapshot: dict | None, events: list[Event] | list[dict] | None, extractionContext: dict | None) -> dict[str, Any]:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    ctx = extractionContext if isinstance(extractionContext, dict) else {}
    evs = list(events or [])
    failures: list[dict[str, str]] = []
    failure_codes: set[str] = set()

    computed_gap = _compute_max_gap_days(evs)
    reported_gap = _max_reported_gap_days(ctx)
    gap_inconsistent = reported_gap is not None and reported_gap != computed_gap

    if not _mechanism_and_diagnoses_supported(snapshot, evs):
        _add_failure(failures, failure_codes, "MECHANISM_OR_DIAGNOSIS_UNSUPPORTED")

    if _has_missing_required_procedure_date(evs):
        _add_failure(failures, failure_codes, "PROCEDURE_DATE_MISSING")

    if gap_inconsistent:
        _add_failure(failures, failure_codes, "GAP_STATEMENT_INCONSISTENT")

    billing_status = str(ctx.get("billingStatus") or ctx.get("billing_status") or "").strip().upper()
    billing_partial = billing_status == "PARTIAL"
    billing_ok = _billing_partial_presentation_ok(ctx) if billing_partial else True
    if billing_partial and not billing_ok:
        _add_failure(failures, failure_codes, "BILLING_IMPLIED_COMPLETE")

    contradictions = _internal_contradictions(snapshot, evs, ctx, computed_gap)
    if contradictions:
        _add_failure(failures, failure_codes, "INTERNAL_CONTRADICTION")

    pt_ev = ctx.get("ptEvidence") or ctx.get("pt_evidence") or {}
    pt_verified = None
    pt_reported_max = None
    try:
        if isinstance(pt_ev, dict):
            pt_verified = int(pt_ev.get("verified_pt_count")) if pt_ev.get("verified_pt_count") is not None else None
            pt_reported_max = int(pt_ev.get("reported_pt_count_max")) if pt_ev.get("reported_pt_count_max") is not None else None
    except Exception:
        pt_verified, pt_reported_max = None, None

    if failures:
        status = "BLOCKED"
    elif pt_verified == 0 and (pt_reported_max or 0) > 0:
        status = "BLOCKED"
    elif pt_reported_max is not None and pt_reported_max >= 10 and (pt_verified or 0) < 3:
        status = "REVIEW_RECOMMENDED"
    elif billing_partial:
        status = "REVIEW_RECOMMENDED"
    else:
        status = "VERIFIED"

    return {
        "version": "litigation_safe_v1",
        "status": status,
        "failure_reasons": failures,
        "billing_partial_disclosed": bool(billing_partial and billing_ok),
        "checks": {
            "mechanism_and_diagnosis_supported": "MECHANISM_OR_DIAGNOSIS_UNSUPPORTED" not in failure_codes,
            "procedure_dates_complete": "PROCEDURE_DATE_MISSING" not in failure_codes,
            "gap_statement_consistent": "GAP_STATEMENT_INCONSISTENT" not in failure_codes,
            "billing_not_implied_complete": "BILLING_IMPLIED_COMPLETE" not in failure_codes,
            "no_internal_contradictions": "INTERNAL_CONTRADICTION" not in failure_codes,
        },
        "computed": {
            "max_gap_days": computed_gap,
            "has_gap_gt_45": computed_gap > 45,
            "reported_max_gap_days": reported_gap,
            "pt_count_candidates": _pt_count_candidates(snapshot, evs, ctx),
            "contradiction_details": contradictions,
            "pt_verified_count": pt_verified,
            "pt_reported_count_max": pt_reported_max,
        },
    }


def _add_failure(out: list[dict[str, str]], seen: set[str], code: str) -> None:
    if code in seen:
        return
    seen.add(code)
    out.append({"code": code, "message": _REASON_MESSAGES.get(code, code)})


def _event_text(event: Event | dict) -> str:
    parts: list[str] = []
    if isinstance(event, dict):
        for k in ("reason_for_visit", "chief_complaint", "author_name", "author_role"):
            v = event.get(k)
            if v:
                parts.append(str(v))
        for k in ("facts", "diagnoses", "procedures", "exam_findings", "treatment_plan"):
            for f in event.get(k) or []:
                if isinstance(f, dict):
                    parts.append(str(f.get("text") or ""))
                else:
                    parts.append(str(getattr(f, "text", "") or ""))
        return " ".join(parts).lower()
    for k in ("reason_for_visit", "chief_complaint", "author_name", "author_role"):
        v = getattr(event, k, None)
        if v:
            parts.append(str(v))
    for k in ("facts", "diagnoses", "procedures", "exam_findings", "treatment_plan"):
        for f in (getattr(event, k, None) or []):
            parts.append(str(getattr(f, "text", "") or ""))
    return " ".join(parts).lower()


def _event_citation_ids(event: Event | dict) -> set[str]:
    ids: set[str] = set()
    if isinstance(event, dict):
        for cid in event.get("citation_ids") or []:
            ids.add(str(cid))
        for k in ("facts", "diagnoses", "procedures", "exam_findings", "treatment_plan"):
            for f in event.get(k) or []:
                if isinstance(f, dict):
                    if f.get("citation_id"):
                        ids.add(str(f.get("citation_id")))
                    for cid in f.get("citation_ids") or []:
                        ids.add(str(cid))
        return ids
    for cid in (getattr(event, "citation_ids", None) or []):
        ids.add(str(cid))
    for k in ("facts", "diagnoses", "procedures", "exam_findings", "treatment_plan"):
        for f in (getattr(event, k, None) or []):
            if getattr(f, "citation_id", None):
                ids.add(str(getattr(f, "citation_id")))
            for cid in (getattr(f, "citation_ids", None) or []):
                ids.add(str(cid))
    return ids


def _mechanism_terms(mechanism: str) -> set[str]:
    low = mechanism.lower().strip()
    for needle, terms in _MECH_TERM_MAP.items():
        if needle in low:
            return terms
    toks = {t for t in re.findall(r"[a-z0-9-]+", low) if len(t) >= 4 and t not in {"vehicle", "motor"}}
    return toks


def _mechanism_and_diagnoses_supported(snapshot: dict[str, Any], events: list[Event] | list[dict]) -> bool:
    mechanism = str(snapshot.get("mechanism") or "").strip()
    if mechanism and mechanism.lower() not in {"not clearly extracted from packet", "not established"}:
        mech_cids = {str(c) for c in (snapshot.get("mechanism_citation_ids") or []) if str(c)}
        terms = _mechanism_terms(mechanism)
        found = False
        if mech_cids and terms:
            for ev in events:
                ev_cids = _event_citation_ids(ev)
                if not ev_cids or not (ev_cids & mech_cids):
                    continue
                txt = _event_text(ev)
                if any(t in txt for t in terms):
                    found = True
                    break
        if not found:
            return False

    snapshot_diagnoses = [str(x or "").strip() for x in (snapshot.get("diagnoses") or []) if str(x or "").strip()]
    if not snapshot_diagnoses:
        return True
    extracted_icd: set[str] = set()
    extracted_dx_texts: list[str] = []
    for ev in events:
        coding = ev.get("coding") if isinstance(ev, dict) else getattr(ev, "coding", {})
        if isinstance(coding, dict):
            for code in coding.get("icd10") or []:
                extracted_icd.add(str(code).upper())
        dx_pool = ev.get("diagnoses") if isinstance(ev, dict) else getattr(ev, "diagnoses", None)
        for dx in (dx_pool or []):
            text = str((dx.get("text") if isinstance(dx, dict) else getattr(dx, "text", "")) or "").strip().lower()
            if text:
                extracted_dx_texts.append(text)
    for diag in snapshot_diagnoses:
        codes = {c.upper() for c in re.findall(r"\b[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?\b", diag)}
        low = diag.lower()
        if codes:
            if not codes.issubset(extracted_icd):
                return False
            continue
        if not any(low in txt or txt in low for txt in extracted_dx_texts):
            return False
    return True


def _event_type_value(event: Event | dict) -> str:
    raw = event.get("event_type") if isinstance(event, dict) else getattr(event, "event_type", None)
    if hasattr(raw, "value"):
        return str(raw.value)
    if isinstance(raw, dict):
        return str(raw.get("value") or "")
    return str(raw or "")


def _event_dates(event: Event | dict) -> tuple[date | None, date | None]:
    d = event.get("date") if isinstance(event, dict) else getattr(event, "date", None)
    if not d:
        return (None, None)
    val = d.get("value") if isinstance(d, dict) else getattr(d, "value", None)
    if isinstance(val, date):
        return (val, val)
    if isinstance(val, dict):
        s = val.get("start")
        e = val.get("end")
        return (s if isinstance(s, date) else None, e if isinstance(e, date) else None)
    s = getattr(val, "start", None)
    e = getattr(val, "end", None)
    return (s if isinstance(s, date) else None, e if isinstance(e, date) else None)


def _event_is_procedure_sensitive(event: Event | dict) -> bool:
    et = _event_type_value(event).lower()
    if et in {"imaging_study", "procedure"}:
        return True
    txt = _event_text(event)
    return bool(re.search(r"\b(injection|epidural|esi|surgery|operative|arthroscop|fusion)\b", txt, re.I))


def _has_missing_required_procedure_date(events: list[Event] | list[dict]) -> bool:
    for ev in events:
        if not _event_is_procedure_sensitive(ev):
            continue
        s, e = _event_dates(ev)
        if s is None and e is None:
            return True
    return False


def _treatment_events_for_gap(events: list[Event] | list[dict]) -> list[tuple[date, str]]:
    rows: list[tuple[date, str]] = []
    for ev in events:
        et = _event_type_value(ev).lower()
        if et in {"billing_event", "administrative", "referenced_prior_event", "other_event"}:
            continue
        s, _e = _event_dates(ev)
        if s is None:
            continue
        rows.append((s, et))
    rows.sort(key=lambda x: x[0])
    return rows


def _compute_max_gap_days(events: list[Event] | list[dict]) -> int:
    dated = _treatment_events_for_gap(events)
    if len(dated) < 2:
        return 0
    max_gap = 0
    prev = dated[0][0]
    for d, _et in dated[1:]:
        delta = (d - prev).days
        if delta > max_gap:
            max_gap = delta
        prev = d
    return max_gap


def _max_reported_gap_days(ctx: dict[str, Any]) -> int | None:
    vals: list[int] = []
    for g in (ctx.get("gaps") or []):
        if isinstance(g, Gap):
            vals.append(int(getattr(g, "duration_days", 0) or 0))
        elif isinstance(g, dict):
            vals.append(int(g.get("duration_days") or g.get("gap_days") or 0))
    mr = ctx.get("missingRecords") or ctx.get("missing_records") or {}
    if isinstance(mr, dict):
        for g in (mr.get("gaps") or []):
            if not isinstance(g, dict):
                continue
            vals.append(int(g.get("gap_days") or g.get("duration_days") or 0))
    vals = [v for v in vals if v >= 0]
    if not vals:
        return None
    return max(vals)


def _billing_partial_presentation_ok(ctx: dict[str, Any]) -> bool:
    bp = ctx.get("billingPresentation") or ctx.get("billing_presentation") or {}
    if not isinstance(bp, dict):
        bp = {}
    visible_incomplete = bool(bp.get("visibleIncompleteDisclosure", True))
    no_global_specials = bool(bp.get("noGlobalTotalSpecials", True))
    partial_label = bool(bp.get("partialTotalsLabeled", True))
    return visible_incomplete and no_global_specials and partial_label


def _extract_pt_counts_from_text(text: str) -> list[int]:
    out: list[int] = []
    for m in re.finditer(r"\bPT\s+(?:visits|sessions)\s*(?::|-)?\s*(\d+)\b", text, re.I):
        out.append(int(m.group(1)))
    for m in re.finditer(r"\b(\d+)\s+encounters\b", text, re.I):
        out.append(int(m.group(1)))
    return out


def _pt_count_candidates(snapshot: dict[str, Any], events: list[Event] | list[dict], ctx: dict[str, Any]) -> list[int]:
    vals: set[int] = set()
    try:
        if snapshot.get("pt_total_encounters") is not None:
            vals.add(int(snapshot.get("pt_total_encounters")))
    except Exception:
        pass
    for ev in events:
        if _event_type_value(ev).lower() != "pt_visit":
            continue
        txt = _event_text(ev)
        for n in _extract_pt_counts_from_text(txt):
            vals.add(n)
    for n in (ctx.get("ptCountCandidates") or ctx.get("pt_count_candidates") or []):
        try:
            vals.add(int(n))
        except Exception:
            continue
    return sorted(vals)


def _internal_contradictions(snapshot: dict[str, Any], events: list[Event] | list[dict], ctx: dict[str, Any], computed_gap: int) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []

    pt_counts = _pt_count_candidates(snapshot, events, ctx)
    if len(set(pt_counts)) > 1:
        details.append({"kind": "pt_count_conflict", "values": pt_counts})

    stated_max_gap = ctx.get("statedMaxGapDays") or ctx.get("stated_max_gap_days")
    if stated_max_gap is not None:
        try:
            stated = int(stated_max_gap)
            if stated != computed_gap:
                details.append({"kind": "gap_mismatch", "computed": computed_gap, "stated": stated})
        except Exception:
            pass

    provider_sections = ctx.get("providerSections") or ctx.get("provider_sections") or {}
    if isinstance(provider_sections, dict):
        unresolved = set()
        resolved = set()
        for section, names in provider_sections.items():
            for name in names or []:
                low = str(name or "").strip().lower()
                if not low:
                    continue
                if low in {"unknown", "provider not clearly identified", "provider not identified"}:
                    unresolved.add(str(section))
                else:
                    resolved.add(str(section))
        if unresolved and resolved:
            details.append({"kind": "provider_resolution_conflict", "unresolved_sections": sorted(unresolved), "resolved_sections": sorted(resolved)})

    numeric_aggs = ctx.get("numericAggregates") or ctx.get("numeric_aggregates") or {}
    if isinstance(numeric_aggs, dict):
        for key, vals in numeric_aggs.items():
            parsed = []
            for v in vals or []:
                try:
                    parsed.append(float(v))
                except Exception:
                    continue
            parsed = sorted(set(parsed))
            if len(parsed) > 1:
                details.append({"kind": "numeric_conflict", "key": str(key), "values": parsed})

    return details
