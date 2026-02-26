from __future__ import annotations

import re
from typing import Any

from packages.shared.models import Citation, Page

_EXPLICIT_FACILITY_RE = re.compile(r"\b(?:facility|clinic|practice|location)\s*[:\-]\s*([^\n|]{3,120})", re.I)
_EXPLICIT_PROVIDER_RE = re.compile(r"\b(?:provider|treating provider|rendering provider|therapist)\s*[:\-]\s*([^\n|]{3,120})", re.I)
_PHONE_RE = re.compile(r"(?:\+?1\s*[-.]?\s*)?(?:\(?\d{3}\)?\s*[-.]?\s*)\d{3}\s*[-.]?\s*\d{4}")
_FAX_RE = re.compile(r"\bfax\b\s*[:#-]?\s*([\d()\-\.\s]{10,20})", re.I)
_FAX_FROM_RE = re.compile(r"\bfrom\s*[:\-]\s*([^\n]{3,120})", re.I)
_ADDRESS_RE = re.compile(r"\b\d{2,6}\s+[A-Za-z0-9][A-Za-z0-9 .#-]{2,}\b(?:suite|ste\.?|road|rd\.?|street|st\.?|avenue|ave\.?|blvd|drive|dr\.?|lane|ln\.?)", re.I)
_CITY_STATE_ZIP_RE = re.compile(r"\b[A-Za-z .'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
_CLINICISH_RE = re.compile(r"\b(physical therapy|rehab|rehabilitation|therapy center|therapy clinic|medical center|clinic|hospital)\b", re.I)
_UPPER_LINE_RE = re.compile(r"^[A-Z][A-Z0-9 &'.,()/-]{4,}$")
_NOISE_LINE_RE = re.compile(r"\b(page\s+\d+|fax id|mrn[:\s]|dob[:\s]|date[:\s]\d)\b", re.I)


def resolve_document_identity(document_pages: list[Page], citations: list[Citation] | None = None) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for p in (document_pages or []):
        if not p:
            continue
        page_cands = resolve_page_identity(p, citations=citations)
        candidates.extend(page_cands)
    return choose_best(candidates)


def resolve_page_identity(page: Page, citations: list[Citation] | None = None) -> list[dict[str, Any]]:
    text = str(getattr(page, "text", "") or "")
    if not text.strip():
        return []
    page_no = int(getattr(page, "page_number", 0) or 0)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    top_lines = lines[:10]
    top_blob = "\n".join(top_lines)
    page_citation_ids = [str(c.citation_id) for c in (citations or []) if int(getattr(c, "page_number", 0) or 0) == page_no and getattr(c, "citation_id", None)]

    candidates: list[dict[str, Any]] = []

    # Explicit labels
    fac_m = _EXPLICIT_FACILITY_RE.search(text)
    prov_m = _EXPLICIT_PROVIDER_RE.search(text)
    if fac_m or prov_m:
        facility = _clean_name(fac_m.group(1) if fac_m else None)
        provider = _clean_name(prov_m.group(1) if prov_m else None)
        conf = 0.6
        if facility and _CLINICISH_RE.search(facility):
            conf += 0.2
        candidates.append(_candidate(
            provider_name=provider,
            facility_name=facility,
            phone=_first_phone(text),
            address=_extract_address(text),
            resolved_from="page_header",
            confidence=conf,
            page_number=page_no,
            evidence_citation_ids=page_citation_ids[:8],
            resolution_reason=("explicit_label"),
        ))

    # Letterhead / header blocks
    header_name = _extract_header_name(top_lines)
    addr = _extract_address(top_blob)
    phone = _first_phone(top_blob)
    has_city = bool(_CITY_STATE_ZIP_RE.search(top_blob))
    if header_name and (_CLINICISH_RE.search(header_name) or (addr and (phone or has_city))):
        conf = 0.0
        if _CLINICISH_RE.search(header_name):
            conf += 0.4
        if addr and (phone or has_city):
            conf += 0.3
        elif phone:
            conf += 0.15
        candidates.append(_candidate(
            provider_name=(None if _CLINICISH_RE.search(header_name) else header_name),
            facility_name=(header_name if _CLINICISH_RE.search(header_name) else None),
            phone=phone,
            address=addr,
            resolved_from="document_header",
            confidence=conf,
            page_number=page_no,
            evidence_citation_ids=page_citation_ids[:8],
            resolution_reason="letterhead_header",
        ))

    # PT-specific named mentions on page top/body
    for ln in top_lines[:6]:
        if _NOISE_LINE_RE.search(ln):
            continue
        if _CLINICISH_RE.search(ln) and len(ln) <= 120:
            candidates.append(_candidate(
                provider_name=None,
                facility_name=_clean_name(ln),
                phone=_first_phone(top_blob),
                address=_extract_address(top_blob),
                resolved_from="page_header",
                confidence=0.4 + (0.3 if (_extract_address(top_blob) and _first_phone(top_blob)) else 0.0),
                page_number=page_no,
                evidence_citation_ids=page_citation_ids[:8],
                resolution_reason="pt_clinic_header_line",
            ))
            break

    # Fax metadata (low confidence unless paired)
    fax_phone = None
    if (fm := _FAX_RE.search(text)):
        fax_phone = _normalize_phone(fm.group(1))
    elif (ph := _FIND_PHONE_NEAR_FAX(text)):
        fax_phone = ph
    elif "fax" in text.lower():
        fax_phone = _first_phone(text)
    fax_from_name = None
    if (ff := _FAX_FROM_RE.search(text)):
        fax_from_name = _clean_name(ff.group(1))
    if fax_phone or fax_from_name:
        conf = 0.1
        if fax_from_name and _CLINICISH_RE.search(fax_from_name):
            conf += 0.25
        if fax_phone and fax_from_name:
            conf += 0.1
        elif fax_phone and not fax_from_name:
            conf -= 0.3
        candidates.append(_candidate(
            provider_name=None,
            facility_name=(fax_from_name if fax_from_name and _CLINICISH_RE.search(fax_from_name) else None),
            phone=fax_phone,
            address=None,
            resolved_from="fax_metadata",
            confidence=conf,
            page_number=page_no,
            evidence_citation_ids=page_citation_ids[:8],
            resolution_reason=("fax_from" if fax_from_name else "fax_phone_only"),
        ))

    return [c for c in candidates if c]


def choose_best(candidates: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    rows = [c for c in (candidates or []) if isinstance(c, dict)]
    if not rows:
        return None
    ranked = sorted(rows, key=lambda c: (
        -float(c.get("confidence") or 0.0),
        0 if c.get("facility_name") else 1,
        0 if c.get("provider_name") else 1,
        {"page_header": 0, "document_header": 1, "fax_metadata": 2, "inferred": 3}.get(str(c.get("resolved_from") or "inferred"), 9),
        int(c.get("page_number") or 0),
    ))
    best = dict(ranked[0])
    best["confidence"] = round(max(0.0, min(1.0, float(best.get("confidence") or 0.0))), 3)
    return best


def build_page_identity_map(
    *,
    pages: list[Page],
    citations: list[Citation] | None = None,
) -> dict[int, dict[str, Any]]:
    by_doc: dict[str, list[Page]] = {}
    for p in (pages or []):
        by_doc.setdefault(str(getattr(p, "source_document_id", "") or ""), []).append(p)
    doc_best: dict[str, dict[str, Any] | None] = {}
    page_direct: dict[int, dict[str, Any] | None] = {}
    for doc_id, doc_pages in by_doc.items():
        doc_pages_sorted = sorted(doc_pages, key=lambda p: int(getattr(p, "page_number", 0) or 0))
        # Focus on first page and likely letterhead pages
        focus = []
        seen = set()
        for p in doc_pages_sorted:
            pg = int(getattr(p, "page_number", 0) or 0)
            ptype = str(getattr(p, "page_type", "") or "").lower()
            if pg == int(getattr(doc_pages_sorted[0], "page_number", 0) or 0) or any(k in ptype for k in ["pt_note", "discharge", "billing"]):
                if pg not in seen:
                    focus.append(p)
                    seen.add(pg)
        if not focus:
            focus = doc_pages_sorted[:3]
        all_doc_candidates: list[dict[str, Any]] = []
        for p in focus:
            cands = resolve_page_identity(p, citations=citations)
            direct = choose_best(cands)
            page_direct[int(getattr(p, "page_number", 0) or 0)] = direct
            all_doc_candidates.extend(cands)
        doc_best[doc_id] = choose_best(all_doc_candidates)
        # Also capture direct candidates for non-focus pages lazily
        for p in doc_pages_sorted:
            pg = int(getattr(p, "page_number", 0) or 0)
            if pg in page_direct:
                continue
            page_direct[pg] = choose_best(resolve_page_identity(p, citations=citations))

    resolved: dict[int, dict[str, Any]] = {}
    for p in (pages or []):
        pg = int(getattr(p, "page_number", 0) or 0)
        doc_id = str(getattr(p, "source_document_id", "") or "")
        direct = page_direct.get(pg)
        if direct and float(direct.get("confidence") or 0.0) >= 0.75:
            resolved[pg] = _finalize_identity(direct)
            continue
        doc_ident = doc_best.get(doc_id)
        if doc_ident and float(doc_ident.get("confidence") or 0.0) >= 0.60:
            inherited = dict(doc_ident)
            inherited["resolved_from"] = "inferred"
            inherited["inherited_from_page"] = int(doc_ident.get("page_number") or 0)
            inherited["page_number"] = pg
            inherited["confidence"] = round(max(0.0, min(1.0, float(doc_ident.get("confidence") or 0.0) - 0.05)), 3)
            inherited["resolution_reason"] = "document_scope_propagation"
            resolved[pg] = _finalize_identity(inherited)
            continue
        if direct:
            # Keep low-confidence candidate visible for renderer labeling, but flagged.
            resolved[pg] = _finalize_identity(direct)
        else:
            resolved[pg] = {
                "provider_name": None,
                "facility_name": None,
                "phone": None,
                "address": None,
                "resolved_from": None,
                "confidence": 0.0,
                "page_number": pg,
                "evidence_citation_ids": [],
                "resolution_reason": "no_candidate",
            }
    return resolved


def augment_provider_resolution_quality(
    base_metric: dict[str, Any] | None,
    *,
    pt_encounters: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    metric = dict(base_metric or {})
    pt_rows = [r for r in (pt_encounters or []) if isinstance(r, dict)]
    total = len(pt_rows)
    fac_resolved = 0
    prov_resolved = 0
    unresolved_examples: list[dict[str, Any]] = []
    for row in pt_rows:
        fac = str(row.get("facility_name") or "").strip()
        prov = str(row.get("provider_name") or "").strip()
        fac_unknown = fac.lower() in {"", "unknown facility", "unknown"}
        prov_unknown = prov.lower() in {"", "unknown provider", "unknown"}
        if not fac_unknown:
            fac_resolved += 1
        if not prov_unknown:
            prov_resolved += 1
        if fac_unknown or prov_unknown:
            if len(unresolved_examples) < 6:
                unresolved_examples.append(
                    {
                        "page_number": int(row.get("page_number") or 0),
                        "encounter_date": str(row.get("encounter_date") or ""),
                        "provider_name": prov or "Unknown Provider",
                        "facility_name": fac or "Unknown Facility",
                        "provider_why_unresolved": ((row.get("provider_resolution") or {}).get("why_unresolved") if isinstance(row.get("provider_resolution"), dict) else None),
                        "facility_why_unresolved": ((row.get("facility_resolution") or {}).get("why_unresolved") if isinstance(row.get("facility_resolution"), dict) else None),
                    }
                )
    fac_ratio = round((fac_resolved / total), 4) if total else 1.0
    prov_ratio = round((prov_resolved / total), 4) if total else 1.0
    gate = {"status": "warn", "reason": None}
    if total >= 10 and fac_ratio < 0.50:
        gate = {"status": "BLOCKED", "reason": "PT_FACILITY_RESOLUTION_RATIO_LT_050"}
    elif total >= 10 and fac_ratio < 0.90:
        gate = {"status": "REVIEW_RECOMMENDED", "reason": "PT_FACILITY_RESOLUTION_RATIO_LT_090"}
    pt_section = {
        "pt_ledger_rows_total": total,
        "pt_facility_resolved": fac_resolved,
        "pt_provider_resolved": prov_resolved,
        "pt_facility_resolved_ratio": fac_ratio,
        "pt_provider_resolved_ratio": prov_ratio,
        "pt_provider_facility_gate": gate,
        "top_unresolved_examples": unresolved_examples,
    }
    metric["pt_ledger"] = pt_section
    unresolved_by_family = dict(metric.get("unresolved_by_family") or {})
    if total and fac_resolved < total:
        unresolved_by_family["pt_encounter_facility"] = total - fac_resolved
    if total and prov_resolved < total:
        unresolved_by_family["pt_encounter_provider"] = total - prov_resolved
    metric["unresolved_by_family"] = {k: unresolved_by_family[k] for k in sorted(unresolved_by_family)}
    metric["version"] = str(metric.get("version") or "1.1")
    metric["scope"] = str(metric.get("scope") or "export_projection_rows")
    return metric


def _finalize_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    out = dict(candidate)
    out["provider_name"] = _clean_name(out.get("provider_name")) or None
    out["facility_name"] = _clean_name(out.get("facility_name")) or None
    out["phone"] = _normalize_phone(out.get("phone")) if out.get("phone") else None
    out["address"] = _clean_name(out.get("address")) or None
    out["confidence"] = round(max(0.0, min(1.0, float(out.get("confidence") or 0.0))), 3)
    out["evidence_citation_ids"] = [str(x) for x in (out.get("evidence_citation_ids") or []) if str(x).strip()][:8]
    return out


def _candidate(**kwargs: Any) -> dict[str, Any]:
    row = dict(kwargs)
    row["confidence"] = round(max(0.0, min(1.0, float(row.get("confidence") or 0.0))), 3)
    return row


def _clean_name(value: Any) -> str | None:
    s = re.sub(r"\s+", " ", str(value or "").strip())
    s = re.sub(r"^[\-|:]+\s*", "", s)
    s = re.sub(r"\s*[|]+.*$", "", s)
    s = re.sub(r"\b(?:phone|fax)\b.*$", "", s, flags=re.I)
    s = s.strip(" ,;:-")
    if not s or len(s) < 3:
        return None
    if len(s) > 140:
        s = s[:140].rstrip()
    return s


def _first_phone(text: str) -> str | None:
    m = _PHONE_RE.search(text or "")
    return _normalize_phone(m.group(0)) if m else None


def _normalize_phone(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def _extract_address(text: str) -> str | None:
    if not text:
        return None
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    for i, ln in enumerate(lines[:12]):
        if _ADDRESS_RE.search(ln):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt and _CITY_STATE_ZIP_RE.search(nxt):
                return f"{ln}; {nxt}"
            return ln
    m = _ADDRESS_RE.search(text)
    return m.group(0).strip() if m else None


def _extract_header_name(lines: list[str]) -> str | None:
    for ln in (lines or [])[:6]:
        if _NOISE_LINE_RE.search(ln):
            continue
        if _UPPER_LINE_RE.match(ln) and len(ln) <= 120:
            return _clean_name(ln)
        if _CLINICISH_RE.search(ln) and len(ln) <= 120:
            return _clean_name(ln)
    return None


def _FIND_PHONE_NEAR_FAX(text: str) -> str | None:
    for ln in str(text or "").splitlines()[:10]:
        if "fax" in ln.lower():
            ph = _first_phone(ln)
            if ph:
                return ph
    return None
