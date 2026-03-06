from __future__ import annotations

import re
from typing import Any

from packages.shared.models import Citation

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_PAGE_RE = re.compile(r"(?i)\bp\.\s*(\d+)\b")
_LEAD_LABEL_RE = re.compile(r"^\s*(diagnosis|symptom|treatment|procedure|finding|impression|assessment)\s*:\s*", re.I)
_STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "has",
    "have",
    "that",
    "the",
    "this",
    "with",
    "was",
    "were",
    "noted",
    "documented",
    "patient",
    "presented",
    "primary",
}
_NEGATION_RE = re.compile(r"\b(no|not|denies|denied|without|negative for)\b", re.I)


def _clean_text(text: str) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    s = _LEAD_LABEL_RE.sub("", s)
    return s.strip()


def _tokenize(text: str) -> set[str]:
    tokens = {tok for tok in _TOKEN_RE.findall(_clean_text(text).lower()) if tok not in _STOPWORDS}
    return tokens


def lexical_overlap_ratio(a: str, b: str) -> float:
    left = _tokenize(a)
    right = _tokenize(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left))


def _negation_mismatch(a: str, b: str) -> bool:
    return bool(_NEGATION_RE.search(a or "")) != bool(_NEGATION_RE.search(b or ""))


def _resolve_row_citations(row: dict[str, Any], by_id: dict[str, Citation], by_page: dict[int, list[Citation]]) -> list[Citation]:
    resolved: list[Citation] = []
    seen: set[str] = set()

    for anchor in list(row.get("citation_anchors") or []):
        cid = str((anchor or {}).get("citation_id") or "").strip()
        if cid and cid in by_id and cid not in seen:
            seen.add(cid)
            resolved.append(by_id[cid])

    for raw in list(row.get("citation_ids") or []):
        cid = str(raw or "").strip()
        if cid and cid in by_id and cid not in seen:
            seen.add(cid)
            resolved.append(by_id[cid])

    for raw in list(row.get("citations") or []):
        m = _PAGE_RE.search(str(raw or ""))
        if not m:
            continue
        page_no = int(m.group(1))
        for citation in by_page.get(page_no, []):
            cid = str(getattr(citation, "citation_id", "") or "").strip()
            if cid and cid not in seen:
                seen.add(cid)
                resolved.append(citation)

    return resolved


def assess_claim_row_fidelity(
    claim_rows: list[dict[str, Any]],
    citations: list[Citation],
    *,
    min_overlap: float = 0.12,
) -> dict[str, Any]:
    by_id = {str(getattr(c, "citation_id", "") or ""): c for c in (citations or []) if str(getattr(c, "citation_id", "") or "")}
    by_page: dict[int, list[Citation]] = {}
    for citation in citations or []:
        try:
            page_no = int(getattr(citation, "page_number", 0) or 0)
        except Exception:
            page_no = 0
        if page_no > 0:
            by_page.setdefault(page_no, []).append(citation)

    total = len(claim_rows or [])
    anchored = 0
    text_backed = 0
    suspect_rows: list[dict[str, Any]] = []

    for row in claim_rows or []:
        claim_text = str(row.get("assertion") or row.get("text") or "").strip()
        resolved = _resolve_row_citations(row, by_id, by_page)
        if resolved:
            anchored += 1
        ranked: list[tuple[float, Citation]] = []
        for citation in resolved:
            snippet = str(getattr(citation, "snippet", "") or "").strip()
            if not snippet:
                continue
            ranked.append((lexical_overlap_ratio(claim_text, snippet), citation))
        ranked.sort(key=lambda item: (item[0], str(getattr(item[1], "citation_id", ""))), reverse=True)
        if ranked and ranked[0][0] >= min_overlap and not _negation_mismatch(claim_text, str(getattr(ranked[0][1], "snippet", "") or "")):
            text_backed += 1
            continue
        if resolved:
            best_overlap = ranked[0][0] if ranked else 0.0
            suspect_rows.append(
                {
                    "id": str(row.get("id") or ""),
                    "event_id": str(row.get("event_id") or ""),
                    "claim_type": str(row.get("claim_type") or ""),
                    "best_overlap": round(best_overlap, 4),
                    "citations": [str(getattr(c, "citation_id", "") or "") for _, c in ranked[:3]] if ranked else [str(getattr(c, "citation_id", "") or "") for c in resolved[:3]],
                    "assertion": claim_text[:240],
                }
            )

    anchored_ratio = round((anchored / total), 4) if total else 1.0
    text_backed_ratio = round((text_backed / total), 4) if total else 1.0
    suspect_ratio = round((len(suspect_rows) / max(1, anchored)), 4) if anchored else 0.0

    return {
        "claim_rows_total": total,
        "claim_rows_anchored": anchored,
        "claim_row_anchor_ratio": anchored_ratio,
        "claim_rows_text_backed": text_backed,
        "claim_row_text_backed_ratio": text_backed_ratio,
        "drift_suspect_count": len(suspect_rows),
        "drift_suspect_ratio": suspect_ratio,
        "drift_review_required": bool(suspect_rows),
        "drift_suspects": suspect_rows[:12],
        "min_overlap_threshold": min_overlap,
    }
