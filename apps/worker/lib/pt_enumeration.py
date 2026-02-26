from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from packages.shared.models import Citation, EventDate, Page, PageType, Provider

_PT_MARKER_RE = re.compile(
    r"\b(physical therapy|\bpt\b|therapy visit|therapeutic exercise|manual therapy|home exercise|hep\b|range of motion|\brom\b|plan of care)\b",
    re.I,
)
_PT_ENCOUNTER_MARKER_RE = re.compile(
    r"\b(subjective|objective|assessment|plan|manual therapy|therapeutic exercise|neuromuscular re-?education|gait training|pain\s*(?:level|score)|repetitions|sets?|therapist)\b",
    re.I,
)
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

    for page in pages or []:
        page_no = int(getattr(page, "page_number", 0) or 0)
        text = str(getattr(page, "text", "") or "")
        low = text.lower()
        if not text.strip():
            continue

        page_type = str(getattr(page, "page_type", PageType.OTHER) or "other")
        is_pt_typed = page_type.lower().endswith("pt_note") or page_type.lower() == "PageType.PT_NOTE".lower()
        is_clinical = "clinical_note" in page_type.lower()
        has_pt_marker = bool(_PT_MARKER_RE.search(text))
        if not (is_pt_typed or (is_clinical and has_pt_marker)):
            # still allow summary count extraction from non-PT pages if clearly PT-related summaries
            if has_pt_marker:
                _extract_reported_counts_for_page(pt_reported, page, citations_by_page.get(page_no, []), text)
            continue

        page_citations = citations_by_page.get(page_no, [])
        citation_ids = [str(c.citation_id) for c in page_citations if getattr(c, "citation_id", None)]

        ev_date = _resolve_page_date(page_no, text, dates_by_page)
        provider_name, facility_name = _resolve_provider_facility(page_no, page_provider_map, provider_by_id)

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

        if ev_date and has_pt_marker and not summary_only and citation_ids:
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
                        "dedupe_key": dedupe_key,
                    }
                )

    pt_encounters.sort(key=lambda x: (str(x.get("encounter_date") or "9999-99-99"), int(x.get("page_number") or 0), str(x.get("provider_name") or "")))
    pt_reported = _dedupe_reported_counts(pt_reported)
    pt_reported.sort(key=lambda x: (int(x.get("page_number") or 0), int(x.get("reported_count") or 0)))

    reported_vals = sorted({int(x.get("reported_count") or 0) for x in pt_reported if int(x.get("reported_count") or 0) > 0})
    verified_count = len(pt_encounters)
    reported_min = min(reported_vals) if reported_vals else None
    reported_max = max(reported_vals) if reported_vals else None
    severe_variance = bool(reported_max is not None and reported_max >= 10 and verified_count < 3)
    mismatch = bool(reported_vals and any(v != verified_count for v in reported_vals))

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
        },
    }


def _resolve_page_date(page_no: int, text: str, dates_by_page: dict[int, list[EventDate]]) -> str | None:
    for m in _DATE_LABEL_RE.finditer(text or ""):
        iso = _coerce_date_string(m.group(1))
        if iso:
            return iso
    page_dates = dates_by_page.get(int(page_no), []) or []
    for d in page_dates:
        iso = _event_date_to_iso(d)
        if iso:
            return iso
    for m in _INLINE_DATE_RE.finditer(text or ""):
        iso = _coerce_date_string(m.group(1))
        if iso:
            return iso
    return None


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
