from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from packages.shared.models import Citation, EventDate, Page, PageType, Provider
from apps.worker.lib.provider_resolution_v1 import build_page_identity_map

_PT_MARKER_RE = re.compile(
    r"\b(physical therapy|\bpt\b|therapy visit|therapeutic exercise|manual therapy|home exercise|hep\b|range of motion|\brom\b|plan of care)\b",
    re.I,
)
_PT_KEYWORD_REQUIRED_RE = re.compile(
    r"\b(physical therapy|elite physical therapy|pt visit|therapy visit|therapy session)\b",
    re.I,
)
_PT_ENCOUNTER_MARKER_RE = re.compile(
    r"\b(subjective|objective|assessment|plan|manual therapy|therapeutic exercise|neuromuscular re-?education|gait training|pain\s*(?:level|score)|repetitions|sets?|therapist)\b",
    re.I,
)
_PT_STRONG_STRUCTURE_PATTERNS = [
    re.compile(r"\b(plan of care|\bPOC\b)\b", re.I),
    re.compile(r"\bHEP\b|home exercise program", re.I),
    re.compile(r"\b(oswestry|ndi|lefs|quickdash)\b", re.I),
    re.compile(r"\b(therapist signature|treating therapist|\bDPT\b|\bPTA\b)\b", re.I),
    re.compile(r"\b(therapeutic exercise|manual therapy|neuromuscular re-?education|gait training)\b", re.I),
    re.compile(r"\b(flexion|extension|rotation|sidebend)\b.{0,40}\b(deg|degrees|left|right)\b", re.I),
]
_PT_SUMMARY_COUNT_RE = re.compile(
    r"\b(?:total\s+)?(?:pt\s+)?(?:visits?|encounters?|sessions?)\b[^\n]{0,40}?\b(\d{1,4})\b|\b(\d{1,4})\s+(?:pt\s+)?(?:visits?|encounters?|sessions?)\b",
    re.I,
)
_DATE_LABEL_RE = re.compile(
    r"\b(?:date of service|dos|visit date|date)\s*[:#-]?\s*(\d{1,2}/\d{1,2}/\d{2,4}|20\d{2}-\d{2}-\d{2})\b",
    re.I,
)
_INLINE_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4}|20\d{2}-\d{2}-\d{2})\b")
_SUMMARY_ONLY_HINT_RE = re.compile(r"\b(total visits?|total encounters?|visits completed|number of visits)\b", re.I)
_PT_SUMMARY_PAGE_TITLE_RE = re.compile(r"\b(progress summary|discharge summary|plan of care|re-?evaluation summary)\b", re.I)


def build_pt_evidence_extensions(
    *,
    pages: list[Page],
    dates_by_page: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str] | None,
    citations: list[Citation],
) -> dict[str, Any]:
    provider_by_id = {str(p.provider_id): p for p in (providers or [])}
    citations_by_page: dict[int, list[Citation]] = {}
    for c in citations or []:
        citations_by_page.setdefault(int(c.page_number), []).append(c)

    pt_encounters: list[dict[str, Any]] = []
    pt_reported: list[dict[str, Any]] = []
    seen_dedupe: set[str] = set()
    page_provider_map = page_provider_map or {}
    page_identity_map = build_page_identity_map(pages=pages, citations=citations)

    for page in pages or []:
        page_no = int(getattr(page, "page_number", 0) or 0)
        text = str(getattr(page, "text", "") or "")
        low = text.lower()
        if not text.strip():
            continue

        page_type = str(getattr(page, "page_type", PageType.OTHER) or "other")
        low_page_type = page_type.lower()
        is_pt_typed = low_page_type.endswith("pt_note") or low_page_type == "pagetype.pt_note"
        is_clinical = "clinical_note" in low_page_type
        has_pt_marker = bool(_PT_MARKER_RE.search(text))
        if is_clinical:
            # Hard exclusion: clinical notes (including ED/nursing flowsheets) never count as verified PT encounters.
            if has_pt_marker:
                _extract_reported_counts_for_page(pt_reported, page, citations_by_page.get(page_no, []), text)
            continue
        if not (is_pt_typed or has_pt_marker):
            # still allow summary count extraction from non-PT pages if clearly PT-related summaries
            if has_pt_marker:
                _extract_reported_counts_for_page(pt_reported, page, citations_by_page.get(page_no, []), text)
            continue

        page_citations = citations_by_page.get(page_no, [])
        citation_ids = [str(c.citation_id) for c in page_citations if getattr(c, "citation_id", None)]

        ev_date, ev_date_ambiguous = _resolve_page_date(page_no, text, dates_by_page)
        provider_name, facility_name = _resolve_provider_facility(page_no, page_provider_map, provider_by_id)
        page_identity = page_identity_map.get(page_no) or {}
        provider_name, facility_name, provider_meta, facility_meta = _apply_identity_resolution(
            page_no=page_no,
            base_provider_name=provider_name,
            base_facility_name=facility_name,
            page_identity=page_identity,
            citation_ids=citation_ids,
        )

        summary_counts = _extract_reported_counts_for_page(pt_reported, page, page_citations, text)
        has_encounter_marker = bool(_PT_ENCOUNTER_MARKER_RE.search(text))
        nonempty_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        summary_title_page = bool(nonempty_lines and _PT_SUMMARY_PAGE_TITLE_RE.search(nonempty_lines[0]))
        substantive_marker_count = sum(
            1
            for pat in [
                re.compile(r"\bsubjective\b", re.I),
                re.compile(r"\bassessment\b", re.I),
                re.compile(r"\bplan\b", re.I),
                re.compile(r"\bmanual therapy\b", re.I),
                re.compile(r"\btherapeutic exercise\b", re.I),
                re.compile(r"\bneuromuscular re-?education\b", re.I),
                re.compile(r"\bgait training\b", re.I),
            ]
            if pat.search(text)
        )
        summary_only = bool(
            summary_counts
            and (
                (_SUMMARY_ONLY_HINT_RE.search(text) and not has_encounter_marker)
                or (summary_title_page and substantive_marker_count < 2)
            )
        )

        fallback_allowed = _allow_non_pt_note_primary(page_type=low_page_type, text=text, has_pt_marker=has_pt_marker)
        is_primary_page = is_pt_typed or fallback_allowed
        if ev_date and (not ev_date_ambiguous) and has_pt_marker and not summary_only and is_primary_page and citation_ids:
            snippet_hash = _snippet_hash(text)
            dedupe_key = hashlib.sha1(
                f"{ev_date}|{provider_name}|{facility_name}|{page_no}|{snippet_hash}".encode("utf-8")
            ).hexdigest()
            if dedupe_key not in seen_dedupe:
                seen_dedupe.add(dedupe_key)
                pt_encounters.append(
                    {
                        "encounter_date": ev_date,
                        "provider_name": provider_name,
                        "facility_name": facility_name,
                        "encounter_kind": "PT",
                        "source": "primary",
                        "evidence_citation_ids": citation_ids[:8],
                        "page_number": page_no,
                        "source_document_id": str(getattr(page, "source_document_id", "") or ""),
                        "source_page_type": low_page_type,
                        "dedupe_key": dedupe_key,
                        "provider_resolution": provider_meta,
                        "facility_resolution": facility_meta,
                    }
                )

    pt_encounters = _dedupe_same_day_pt_encounters(pt_encounters)
    pt_encounters.sort(key=lambda x: (str(x.get("encounter_date") or "9999-99-99"), int(x.get("page_number") or 0), str(x.get("provider_name") or "")))
    pt_reported = _dedupe_reported_counts(pt_reported)
    pt_reported.sort(key=lambda x: (int(x.get("page_number") or 0), int(x.get("reported_count") or 0)))

    reported_vals = sorted({int(x.get("reported_count") or 0) for x in pt_reported if int(x.get("reported_count") or 0) > 0})
    verified_count = len(pt_encounters)
    reported_min = min(reported_vals) if reported_vals else None
    reported_max = max(reported_vals) if reported_vals else None
    severe_variance = bool(reported_max is not None and reported_max >= 10 and verified_count < 3)
    mismatch = bool(reported_vals and any(v != verified_count for v in reported_vals))
    date_anomaly = _pt_date_concentration_anomaly(pt_encounters)

    return {
        "pt_encounters": pt_encounters,
        "pt_count_reported": pt_reported,
        "pt_reconciliation": {
            "verified_pt_count": verified_count,
            "reported_pt_counts": reported_vals,
            "reported_pt_count_min": reported_min,
            "reported_pt_count_max": reported_max,
            "variance_flag": mismatch,
            "severe_variance_flag": severe_variance,
            "variance_delta_max_minus_verified": (reported_max - verified_count) if reported_max is not None else None,
            "date_concentration_anomaly": date_anomaly,
        },
        "page_identity_resolution": {
            str(k): v for k, v in sorted(page_identity_map.items())
        },
    }


def _resolve_page_date(page_no: int, text: str, dates_by_page: dict[int, list[EventDate]]) -> tuple[str | None, bool]:
    explicit_hits: list[str] = []
    for m in _DATE_LABEL_RE.finditer(text or ""):
        iso = _coerce_date_string(m.group(1))
        if iso:
            explicit_hits.append(iso)
    if len(set(explicit_hits)) > 1:
        return (sorted(set(explicit_hits))[0], True)
    if explicit_hits:
        return (explicit_hits[0], False)
    page_dates = dates_by_page.get(int(page_no), []) or []
    page_date_hits: list[str] = []
    for d in page_dates:
        iso = _event_date_to_iso(d)
        if iso:
            page_date_hits.append(iso)
    if len(set(page_date_hits)) > 1:
        return (sorted(set(page_date_hits))[0], True)
    if page_date_hits:
        return (page_date_hits[0], False)
    for m in _INLINE_DATE_RE.finditer(text or ""):
        iso = _coerce_date_string(m.group(1))
        if iso:
            return (iso, False)
    return (None, False)


def _event_date_to_iso(d: EventDate | Any) -> str | None:
    val = getattr(d, "value", None)
    if isinstance(val, date):
        return val.isoformat()
    start = getattr(val, "start", None)
    if isinstance(start, date):
        return start.isoformat()
    if isinstance(val, dict):
        s = val.get("start") or val.get("value")
        if isinstance(s, date):
            return s.isoformat()
    return None


def _coerce_date_string(raw: str | None) -> str | None:
    s = str(raw or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yy < 100:
            yy += 2000
        try:
            return date(yy, mm, dd).isoformat()
        except Exception:
            return None
    m = re.fullmatch(r"(20\d{2})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except Exception:
            return None
    return None


def _resolve_provider_facility(page_no: int, page_provider_map: dict[int, str], provider_by_id: dict[str, Provider]) -> tuple[str, str]:
    provider_name = "Unknown Provider"
    facility_name = "Unknown Facility"
    pid = page_provider_map.get(int(page_no))
    if pid and str(pid) in provider_by_id:
        p = provider_by_id[str(pid)]
        norm = str(getattr(p, "normalized_name", "") or getattr(p, "detected_name_raw", "") or "").strip()
        if norm:
            provider_name = norm
            low = norm.lower()
            if any(tok in low for tok in ["therapy", "rehab", "clinic", "hospital", "center", "centre"]):
                facility_name = norm
    return provider_name, facility_name


def _allow_non_pt_note_primary(*, page_type: str, text: str, has_pt_marker: bool) -> bool:
    forbidden = {"clinical_note", "imaging_report", "billing", "billing_page", "lab_report", "discharge_summary", "other"}
    normalized = str(page_type or "").lower()
    for token in forbidden:
        if token in normalized:
            return False
    if not has_pt_marker or not _PT_KEYWORD_REQUIRED_RE.search(text or ""):
        return False
    structure_hits = 0
    for pat in _PT_STRONG_STRUCTURE_PATTERNS:
        if pat.search(text or ""):
            structure_hits += 1
    return structure_hits >= 2


def _apply_identity_resolution(
    *,
    page_no: int,
    base_provider_name: str,
    base_facility_name: str,
    page_identity: dict[str, Any],
    citation_ids: list[str],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    provider_name = base_provider_name
    facility_name = base_facility_name
    conf = float(page_identity.get("confidence") or 0.0) if isinstance(page_identity, dict) else 0.0
    resolved_from = str(page_identity.get("resolved_from") or "") if isinstance(page_identity, dict) else ""
    source_page = int(page_identity.get("inherited_from_page") or page_identity.get("page_number") or page_no) if isinstance(page_identity, dict) else page_no
    evidence_cids = [str(c) for c in (page_identity.get("evidence_citation_ids") or citation_ids or []) if str(c).strip()][:8] if isinstance(page_identity, dict) else [str(c) for c in (citation_ids or [])][:8]
    reason = str(page_identity.get("resolution_reason") or "") if isinstance(page_identity, dict) else ""

    ident_provider = str(page_identity.get("provider_name") or "").strip() if isinstance(page_identity, dict) else ""
    ident_facility = str(page_identity.get("facility_name") or "").strip() if isinstance(page_identity, dict) else ""
    if ident_provider and provider_name.strip().lower() in {"unknown provider", "unknown", ""}:
        provider_name = ident_provider
    if ident_facility and facility_name.strip().lower() in {"unknown facility", "unknown", ""}:
        facility_name = ident_facility
    if ident_facility and provider_name.strip().lower() in {"unknown provider", "unknown", ""} and "therapy" in ident_facility.lower():
        # Facility-only PT letterhead is still useful attribution for the ledger.
        provider_name = ident_facility
    if (not ident_facility) and facility_name.strip().lower() in {"unknown facility", "unknown", ""}:
        prov_low = provider_name.strip().lower()
        if provider_name and prov_low not in {"unknown provider", "unknown"} and any(tok in prov_low for tok in ["therapy", "rehab", "clinic", "hospital", "center", "centre"]):
            facility_name = provider_name

    provider_meta = {
        "resolved_from": (resolved_from or ("page_provider_map" if provider_name and provider_name != "Unknown Provider" else None)),
        "confidence": round(conf if resolved_from else (0.7 if provider_name and provider_name != "Unknown Provider" and base_provider_name != "Unknown Provider" else 0.0), 3),
        "source_page_number": source_page if (resolved_from or (provider_name and provider_name != "Unknown Provider")) else None,
        "evidence_citation_ids": evidence_cids,
        "why_unresolved": (None if provider_name and provider_name != "Unknown Provider" else (reason or "no_provider_candidate")),
    }
    facility_meta = {
        "resolved_from": (resolved_from or ("page_provider_map" if facility_name and facility_name != "Unknown Facility" and base_facility_name != "Unknown Facility" else None)),
        "confidence": round(
            conf if resolved_from else (
                0.65 if (facility_name and facility_name != "Unknown Facility" and base_facility_name == "Unknown Facility" and provider_name == facility_name)
                else (0.6 if facility_name and facility_name != "Unknown Facility" and base_facility_name != "Unknown Facility" else 0.0)
            ),
            3,
        ),
        "source_page_number": source_page if (resolved_from or (facility_name and facility_name != "Unknown Facility")) else None,
        "evidence_citation_ids": evidence_cids,
        "why_unresolved": (None if facility_name and facility_name != "Unknown Facility" else (reason or "no_facility_candidate")),
    }
    if facility_name and facility_name != "Unknown Facility" and provider_name == facility_name and not facility_meta.get("resolved_from"):
        facility_meta["resolved_from"] = "page_provider_map"
        facility_meta["why_unresolved"] = None
    return provider_name, facility_name, provider_meta, facility_meta


def _extract_reported_counts_for_page(out: list[dict[str, Any]], page: Page, page_citations: list[Citation], text: str) -> list[int]:
    page_no = int(getattr(page, "page_number", 0) or 0)
    page_type = str(getattr(page, "page_type", "other") or "other")
    cids = [str(c.citation_id) for c in page_citations if getattr(c, "citation_id", None)]
    found: list[int] = []
    if not cids:
        return found
    for line in [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]:
        low = line.lower()
        if not _PT_MARKER_RE.search(line) and "visit" not in low and "encounter" not in low and "session" not in low:
            continue
        nums = []
        for m in _PT_SUMMARY_COUNT_RE.finditer(line):
            raw = m.group(1) or m.group(2)
            if raw:
                try:
                    nums.append(int(raw))
                except Exception:
                    pass
        for n in nums:
            if n <= 0:
                continue
            out.append(
                {
                    "reported_count": n,
                    "reported_range_low": None,
                    "reported_range_high": None,
                    "report_source_type": _report_source_type(page_type, low),
                    "evidence_citation_ids": cids[:8],
                    "page_number": page_no,
                }
            )
            found.append(n)
    return found


def _report_source_type(page_type: str, low_text: str) -> str:
    low_type = page_type.lower()
    if "discharge" in low_type or "discharge" in low_text:
        return "discharge_summary"
    if "plan of care" in low_text or re.search(r"\bpoc\b", low_text):
        return "plan_of_care"
    if "progress" in low_text:
        return "progress_summary"
    if "pt_note" in low_type:
        return "pt_note_summary"
    return "other"


def _snippet_hash(text: str) -> str:
    core = re.sub(r"\s+", " ", (text or "").strip().lower())[:500]
    return hashlib.sha1(core.encode("utf-8")).hexdigest()


def _dedupe_reported_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for r in rows:
        key = (int(r.get("page_number") or 0), int(r.get("reported_count") or 0), str(r.get("report_source_type") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _norm_name_for_dedupe(v: Any) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", str(v or "").strip().lower())
    s = re.sub(r"\s+", " ", s).strip()
    if s in {"", "unknown provider", "unknown facility", "unknown"}:
        return ""
    return s


def _dedupe_same_day_pt_encounters(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        d = str(row.get("encounter_date") or "")
        prov = _norm_name_for_dedupe(row.get("provider_name"))
        fac = _norm_name_for_dedupe(row.get("facility_name"))
        doc_id = str(row.get("source_document_id") or "")
        if prov or fac:
            key = (d, fac or "__nofac__", prov or "__noprov__")
        else:
            key = (d, f"doc:{doc_id}", "__unknown__")
        grouped.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for _key, group in grouped.items():
        group_sorted = sorted(group, key=lambda r: (int(r.get("page_number") or 0), str(r.get("dedupe_key") or "")))
        rep = dict(group_sorted[0])
        all_cids: list[str] = []
        seen_c: set[str] = set()
        all_pages: list[int] = []
        for r in group_sorted:
            pg = int(r.get("page_number") or 0)
            if pg and pg not in all_pages:
                all_pages.append(pg)
            for cid in (r.get("evidence_citation_ids") or []):
                sc = str(cid).strip()
                if sc and sc not in seen_c:
                    seen_c.add(sc)
                    all_cids.append(sc)
        rep["evidence_citation_ids"] = all_cids[:24]
        rep["contributing_page_numbers"] = sorted(all_pages)
        rep["dedupe_pages_count"] = len(all_pages)
        out.append(rep)
    return out


def _pt_date_concentration_anomaly(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for r in rows or []:
        d = str(r.get("encounter_date") or "").strip()
        if d:
            counts[d] = counts.get(d, 0) + 1
    total = len(rows or [])
    if not counts:
        return {
            "triggered": False,
            "max_date": None,
            "max_date_count": 0,
            "max_date_ratio": 0.0,
            "reason": None,
        }
    max_date, max_count = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    ratio = (max_count / total) if total else 0.0
    triggered = bool(total >= 6 and (max_count >= 4 or ratio >= 0.50))
    return {
        "triggered": triggered,
        "max_date": max_date,
        "max_date_count": max_count,
        "max_date_ratio": round(ratio, 4),
        "reason": ("PT_date_concentration_anomaly" if triggered else None),
    }
