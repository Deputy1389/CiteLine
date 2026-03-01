from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any


_ALLOWED_PAGE_TYPES: dict[str, set[str]] = {
    "mechanism": {"clinical_note"},
    "diagnosis": {"clinical_note", "imaging_report", "pt_note"},
    "imaging_finding": {"imaging_report"},
    "procedure": {"clinical_note", "procedure_note"},
    "pt_claim": {"pt_note"},
}

_THRESHOLDS: dict[str, float] = {
    "mechanism": 0.40,
    "diagnosis": 0.70,
    "imaging_finding": 0.70,
    "procedure": 0.70,
    "pt_claim": 0.70,
}

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "from",
    "this",
    "into",
    "after",
    "before",
    "patient",
    "history",
    "assessment",
    "diagnosis",
    "finding",
    "findings",
    "documented",
    "reported",
}

_HIGH_RISK_QUALIFIERS = [
    "significant",
    "severe",
    "marked",
    "extends",
    "extending",
    "herniation",
    "extrusion",
    "neural foramen",
    "foraminal",
]

_PROMOTED_TO_CLAIM_TYPE = {
    "diagnosis": "diagnosis",
    "imaging": "imaging_finding",
    "procedure": "procedure",
    "visit_count": "pt_claim",
}

_SEVERITY_ORDER = {"PASS": 0, "WARN": 1, "REVIEW_REQUIRED": 2, "BLOCKED": 3}
_PREALIGN_MIN_OVERLAP = {
    "mechanism": 0.20,
    "diagnosis": 0.20,
    "imaging_finding": 0.18,
    "procedure": 0.20,
    "pt_claim": 0.15,
}


def run_claim_context_alignment(
    evidence_graph_payload: dict | None,
    renderer_manifest: dict | None,
) -> dict[str, Any]:
    eg = evidence_graph_payload if isinstance(evidence_graph_payload, dict) else {}
    rm = renderer_manifest if isinstance(renderer_manifest, dict) else {}
    pages = [p for p in (eg.get("pages") or []) if isinstance(p, dict)]
    citations = [c for c in (eg.get("citations") or []) if isinstance(c, dict)]

    page_by_number: dict[int, dict[str, Any]] = {}
    for p in pages:
        try:
            n = int(p.get("page_number"))
        except Exception:
            continue
        page_by_number[n] = p
    citation_by_id = {str(c.get("citation_id") or ""): c for c in citations if str(c.get("citation_id") or "")}

    claims = _extract_snapshot_claims(rm)
    failures: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    max_severity = "PASS"

    for claim in claims:
        result = _evaluate_claim(claim, page_by_number, citation_by_id)
        results.append(result)
        sev = str(result.get("severity") or "PASS")
        if _SEVERITY_ORDER.get(sev, 0) > _SEVERITY_ORDER.get(max_severity, 0):
            max_severity = sev
        if sev != "PASS":
            failures.append(
                {
                    "claim_id": result.get("claim_id"),
                    "claim_type": result.get("claim_type"),
                    "claim_text": result.get("claim_text"),
                    "citations": result.get("citations"),
                    "page_types": result.get("page_types"),
                    "candidate_pages": result.get("candidate_pages"),
                    "best_page": result.get("best_page"),
                    "best_page_type": result.get("best_page_type"),
                    "best_score": result.get("best_score"),
                    "reason_code": result.get("reason_code"),
                    "severity": sev,
                }
            )

    claims_pass = sum(1 for r in results if str(r.get("severity") or "PASS") == "PASS")
    claims_fail = len(results) - claims_pass
    export_status = "PASS"
    if max_severity == "BLOCKED":
        export_status = "BLOCKED"
    elif max_severity == "REVIEW_REQUIRED":
        export_status = "REVIEW_REQUIRED"
    elif max_severity == "WARN":
        export_status = "WARN"

    return {
        "name": "claim_context_alignment",
        "version": "1.0",
        "claims_total": len(results),
        "claims_pass": claims_pass,
        "claims_fail": claims_fail,
        "failures": failures,
        "claims": results,
        "export_status": export_status,
        "PASS": export_status == "PASS",
    }


def _extract_snapshot_claims(rm: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    mechanism = rm.get("mechanism") if isinstance(rm.get("mechanism"), dict) else {}
    mech_val = str((mechanism or {}).get("value") or "").strip()
    if mech_val and re.search(r"\b(motor vehicle|mva|mvc|collision|rear[- ]end|crash|auto accident)\b", mech_val, re.I):
        claims.append(
            {
                "claim_type": "mechanism",
                "claim_text": mech_val,
                "citation_ids": [str(c) for c in ((mechanism or {}).get("citation_ids") or []) if str(c)],
            }
        )
    for idx, pf in enumerate(rm.get("promoted_findings") or []):
        if not isinstance(pf, dict):
            continue
        if not bool(pf.get("headline_eligible", True)):
            continue
        category = str(pf.get("category") or "").strip().lower()
        claim_type = _PROMOTED_TO_CLAIM_TYPE.get(category)
        if not claim_type:
            continue
        label = str(pf.get("label") or "").strip()
        if not label:
            continue
        claims.append(
            {
                "claim_type": claim_type,
                "claim_text": label,
                "citation_ids": [str(c) for c in (pf.get("citation_ids") or []) if str(c)],
                "claim_id_hint": f"{category}:{idx}",
            }
        )
    return claims


def _evaluate_claim(claim: dict[str, Any], page_by_number: dict[int, dict[str, Any]], citation_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    claim_type = str(claim.get("claim_type") or "")
    claim_text = str(claim.get("claim_text") or "").strip()
    citation_ids = [str(c) for c in (claim.get("citation_ids") or []) if str(c)]
    allowed_types = _ALLOWED_PAGE_TYPES.get(claim_type, {"clinical_note"})
    threshold = float(_THRESHOLDS.get(claim_type, 0.70))
    claim_id = _stable_claim_id(claim_type, claim_text, str(claim.get("claim_id_hint") or ""))

    if not citation_ids:
        return _result(
            claim_id, claim_type, claim_text, [], [], [], None, None, None, "missing_citation", "BLOCKED"
        )

    page_records: list[dict[str, Any]] = []
    for cid in citation_ids:
        c = citation_by_id.get(cid)
        if not c:
            continue
        try:
            page_num = int(c.get("page_number"))
        except Exception:
            continue
        page = page_by_number.get(page_num) or {}
        page_type = str(page.get("page_type") or "")
        snippet = str(c.get("snippet") or "").strip()
        page_text = str(page.get("text") or "")
        source_text = snippet or page_text[:1000]
        if claim_type == "mechanism" and page_text:
            if (not snippet) or (not re.search(r"\b(motor vehicle|collision|mva|mvc|rear[- ]end|crash|auto accident)\b", snippet, re.I)):
                source_text = page_text[:1500]
        score = _semantic_score(claim_text, source_text)
        page_records.append(
            {
                "citation_id": cid,
                "page": page_num,
                "page_type": page_type,
                "score": score,
                "snippet": source_text,
                "snippet_overlap": _token_overlap_ratio(claim_text, source_text),
            }
        )

    if not page_records:
        return _result(
            claim_id, claim_type, claim_text, citation_ids, [], [], None, None, None, "missing_citation", "BLOCKED"
        )

    observed_page_types = sorted({str(r.get("page_type") or "") for r in page_records if str(r.get("page_type") or "")})
    allowed_records = [r for r in page_records if str(r.get("page_type") or "") in allowed_types]
    if not allowed_records:
        best_any = max(page_records, key=lambda r: float(r.get("score") or 0.0))
        best_any_score = float(best_any.get("score") or 0.0)
        best_any_overlap = float(best_any.get("snippet_overlap") or 0.0)
        prealign_threshold = float(_PREALIGN_MIN_OVERLAP.get(claim_type, 0.15))
        soft_page_type = best_any_score >= 0.85 and best_any_overlap >= prealign_threshold
        return _result(
            claim_id,
            claim_type,
            claim_text,
            [int(r["page"]) for r in page_records],
            observed_page_types,
            [{"page": int(r["page"]), "page_type": str(r["page_type"]), "score": round(float(r["score"]), 4)} for r in page_records],
            int(best_any["page"]),
            str(best_any["page_type"]),
            round(best_any_score, 4),
            "page_type_mismatch_soft" if soft_page_type else "page_type_mismatch",
            "REVIEW_REQUIRED" if soft_page_type else "BLOCKED",
        )

    # Pre-alignment hard gate: require citation text and minimum lexical overlap before semantic scoring.
    prealign_threshold = float(_PREALIGN_MIN_OVERLAP.get(claim_type, 0.15))
    text_backed_allowed = [r for r in allowed_records if str(r.get("snippet") or "").strip()]
    if not text_backed_allowed:
        best_any = max(allowed_records, key=lambda r: float(r.get("score") or 0.0))
        return _result(
            claim_id,
            claim_type,
            claim_text,
            [int(r["page"]) for r in page_records],
            observed_page_types,
            [{"page": int(r["page"]), "page_type": str(r["page_type"]), "score": round(float(r["score"]), 4)} for r in page_records],
            int(best_any["page"]),
            str(best_any["page_type"]),
            round(float(best_any["score"]), 4),
            "missing_citation",
            "BLOCKED",
        )
    # Preserve overstatement detection priority even when lexical overlap is modest.
    best_semantic_candidate = max(text_backed_allowed, key=lambda r: float(r.get("score") or 0.0))
    if _overstatement_risk(claim_text, str(best_semantic_candidate.get("snippet") or "")):
        return _result(
            claim_id,
            claim_type,
            claim_text,
            [int(r["page"]) for r in page_records],
            observed_page_types,
            [{"page": int(r["page"]), "page_type": str(r["page_type"]), "score": round(float(r["score"]), 4)} for r in page_records],
            int(best_semantic_candidate["page"]),
            str(best_semantic_candidate["page_type"]),
            round(float(best_semantic_candidate.get("score") or 0.0), 4),
            "overstatement_risk",
            "BLOCKED",
        )
    best_overlap_row = max(text_backed_allowed, key=lambda r: float(r.get("snippet_overlap") or 0.0))
    if float(best_overlap_row.get("snippet_overlap") or 0.0) < prealign_threshold:
        return _result(
            claim_id,
            claim_type,
            claim_text,
            [int(r["page"]) for r in page_records],
            observed_page_types,
            [{"page": int(r["page"]), "page_type": str(r["page_type"]), "score": round(float(r["score"]), 4)} for r in page_records],
            int(best_overlap_row["page"]),
            str(best_overlap_row["page_type"]),
            round(float(best_overlap_row.get("score") or 0.0), 4),
            "pre_alignment_overlap_fail",
            "BLOCKED",
        )

    best = max(text_backed_allowed, key=lambda r: float(r.get("score") or 0.0))
    best_score = float(best.get("score") or 0.0)
    best_snippet = str(best.get("snippet") or "")

    if _is_exact_icd_match(claim_text, best_snippet):
        best_score = max(best_score, 1.0)

    overstatement = _overstatement_risk(claim_text, best_snippet)
    if overstatement:
        return _result(
            claim_id,
            claim_type,
            claim_text,
            [int(r["page"]) for r in page_records],
            observed_page_types,
            [{"page": int(r["page"]), "page_type": str(r["page_type"]), "score": round(float(r["score"]), 4)} for r in page_records],
            int(best["page"]),
            str(best["page_type"]),
            round(best_score, 4),
            "overstatement_risk",
            "BLOCKED",
        )

    if best_score < threshold:
        sev = "REVIEW_REQUIRED" if best_score >= max(0.0, threshold - 0.05) else "BLOCKED"
        reason = "semantic_borderline" if sev == "REVIEW_REQUIRED" else "semantic_mismatch"
        return _result(
            claim_id,
            claim_type,
            claim_text,
            [int(r["page"]) for r in page_records],
            observed_page_types,
            [{"page": int(r["page"]), "page_type": str(r["page_type"]), "score": round(float(r["score"]), 4)} for r in page_records],
            int(best["page"]),
            str(best["page_type"]),
            round(best_score, 4),
            reason,
            sev,
        )

    return _result(
        claim_id,
        claim_type,
        claim_text,
        [int(r["page"]) for r in page_records],
        observed_page_types,
        [{"page": int(r["page"]), "page_type": str(r["page_type"]), "score": round(float(r["score"]), 4)} for r in page_records],
        int(best["page"]),
        str(best["page_type"]),
        round(best_score, 4),
        None,
        "PASS",
    )


def _stable_claim_id(claim_type: str, claim_text: str, hint: str) -> str:
    base = f"{claim_type}|{claim_text}|{hint}".encode("utf-8", "ignore")
    return hashlib.sha1(base).hexdigest()[:12]


def _result(
    claim_id: str,
    claim_type: str,
    claim_text: str,
    citations: list[int] | list[str],
    page_types: list[str],
    candidate_pages: list[dict[str, Any]],
    best_page: int | None,
    best_page_type: str | None,
    best_score: float | None,
    reason_code: str | None,
    severity: str,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "claim_text": claim_text,
        "citations": citations,
        "page_types": page_types,
        "candidate_pages": candidate_pages,
        "best_page": best_page,
        "best_page_type": best_page_type,
        "best_score": best_score,
        "reason_code": reason_code,
        "severity": severity,
        "alignment_pass": severity == "PASS",
        "context_pass": severity == "PASS" or reason_code not in {"page_type_mismatch", "missing_citation"},
        "PASS": severity == "PASS",
    }


def _tokens(text: str) -> set[str]:
    toks = {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 2}
    out = {t for t in toks if t not in _STOPWORDS}
    if "mva" in out or "mvc" in out:
        out.update({"motor", "vehicle", "collision"})
    return out


def _semantic_score(a: str, b: str) -> float:
    aa = (a or "").strip().lower()
    bb = (b or "").strip().lower()
    if not aa or not bb:
        return 0.0
    ta = _tokens(aa)
    tb = _tokens(bb)
    jaccard = (len(ta & tb) / len(ta | tb)) if ta and tb else 0.0
    seq = SequenceMatcher(None, aa[:400], bb[:800]).ratio()
    containment_bonus = 0.2 if aa in bb or any(tok in bb for tok in ta if len(tok) >= 4) else 0.0
    return max(0.0, min(1.0, (0.55 * jaccard) + (0.45 * seq) + containment_bonus))


def _token_overlap_ratio(a: str, b: str) -> float:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta))


def _is_exact_icd_match(claim_text: str, snippet: str) -> bool:
    codes = {c.upper() for c in re.findall(r"\b[A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?\b", claim_text or "")}
    if not codes:
        return False
    low = (snippet or "").upper()
    return all(code in low for code in codes)


def _overstatement_risk(claim_text: str, snippet: str) -> bool:
    claim_low = (claim_text or "").lower()
    snippet_low = (snippet or "").lower()
    if not snippet_low:
        return False
    for qual in _HIGH_RISK_QUALIFIERS:
        if qual in claim_low and qual not in snippet_low:
            return True
    return False
