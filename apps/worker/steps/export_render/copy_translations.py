from __future__ import annotations

from typing import Any


_TIER_LABELS = {
    "PASS": "Litigation-Ready",
    "VERIFIED": "Litigation-Ready",
    "REVIEW_REQUIRED": "Attorney Review Recommended",
    "REVIEW_RECOMMENDED": "Attorney Review Recommended",
    "WARN": "Attorney Review Recommended",
    "BLOCKED": "Not Yet Litigation-Safe",
}


_REASON_TEXT = {
    "semantic_mismatch": "Citation language does not directly support this summary phrasing.",
    "semantic_borderline": "Citation support appears close but not sufficiently direct for safe summary phrasing.",
    "page_type_mismatch": "Citation is located outside the expected clinical narrative context for this summary claim.",
    "page_type_mismatch_soft": "Citation is located outside the preferred document section; review recommended.",
    "missing_citation": "No citation is available for this claim.",
    "overstatement_risk": "Summary wording appears stronger than the cited record language.",
    "pre_alignment_overlap_fail": "Claim wording does not have sufficient lexical overlap with the cited record text.",
    "INTERNAL_CONTRADICTION": "Numeric inconsistency was detected between summary counts and dated encounter records.",
    "MECHANISM_OR_DIAGNOSIS_UNSUPPORTED": "Mechanism or diagnosis summary language could not be fully verified in cited clinical narrative context.",
    "PROCEDURE_DATE_MISSING": "A procedure or imaging item is missing a defensible service date in extracted records.",
    "GAP_STATEMENT_INCONSISTENT": "Treatment-gap summary language conflicts with computed gap records.",
    "BILLING_IMPLIED_COMPLETE": "Billing presentation could imply a complete specials total when extraction is partial.",
}


_VULNERABILITY_COPY = {
    "MECHANISM_OR_DIAGNOSIS_UNSUPPORTED": (
        "Snapshot support variance detected",
        "One or more snapshot summary items are not fully supported by the cited record context.",
        "Defense may argue the summary overstates what the cited pages directly establish.",
        "Confirm the cited page language or revise the summary phrasing before relying on it in demand materials.",
    ),
    "PROCEDURE_DATE_MISSING": (
        "Undated procedure or imaging item",
        "A procedure-sensitive event appears without a defensible service date in the extracted record set.",
        "Defense may challenge chronology reliability or timing of intervention.",
        "Confirm the service date from the source page or provider records before using the event as a timeline anchor.",
    ),
    "GAP_STATEMENT_INCONSISTENT": (
        "Treatment-gap summary conflict",
        "Computed gap values and rendered gap statements are not fully aligned.",
        "Defense may use the inconsistency to challenge chronology accuracy.",
        "Reconcile the gap calculation and export wording before production use.",
    ),
    "BILLING_IMPLIED_COMPLETE": (
        "Billing completeness disclosure risk",
        "Billing data appears partial but presentation may imply a complete specials total.",
        "Defense may attack damages credibility if partial extracts are presented as complete totals.",
        "Treat billing as partial and obtain complete billing/EOB support before final damages presentation.",
    ),
    "INTERNAL_CONTRADICTION": (
        "PT visit count variance detected",
        "Summary counts conflict with enumerated dated encounter records.",
        "Defense may argue treatment volume or chronology totals are overstated or unreliable.",
        "Cross-check discharge summaries and provider visit logs, then reconcile the PT totals before export use.",
    ),
}


def attorney_tier_label(status: str | None) -> str:
    key = str(status or "").strip().upper()
    if key not in _TIER_LABELS:
        raise KeyError(f"Missing attorney-facing tier label for status: {key or '<empty>'}")
    return _TIER_LABELS[key]


def attorney_reason_text(code: str | None) -> str:
    key = str(code or "").strip()
    if key not in _REASON_TEXT:
        raise KeyError(f"Missing attorney-facing reason mapping for code: {key or '<empty>'}")
    return _REASON_TEXT[key]


def format_claim_alignment_failure_summary(claim_failures: list[dict[str, Any]] | None) -> str | None:
    failures = [f for f in (claim_failures or []) if isinstance(f, dict)]
    if not failures:
        return None
    reason_counts: dict[str, int] = {}
    for row in failures:
        reason = str(row.get("reason_code") or "").strip() or "unmapped"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    top_reason = max(reason_counts.items(), key=lambda x: (x[1], x[0]))[0]
    try:
        reason_text = attorney_reason_text(top_reason)
    except KeyError:
        reason_text = "Citation support or context verification is incomplete for one or more claims."
    total = len(failures)
    return f"{total} claim(s) require context review. Most common issue: {reason_text}"


def build_defense_vulnerabilities(lsv1: dict[str, Any] | None) -> list[dict[str, str]]:
    payload = lsv1 if isinstance(lsv1, dict) else {}
    out: list[dict[str, str]] = []
    for f in (payload.get("failure_reasons") or []):
        if not isinstance(f, dict):
            continue
        code = str(f.get("code") or "").strip()
        template = _VULNERABILITY_COPY.get(code)
        if not template:
            title = "Record support issue requires attorney review"
            attorney_message = str(f.get("message") or "").strip() or "An export integrity issue requires attorney review before litigation use."
            defense_risk = "Defense may challenge accuracy or support for one or more summary statements."
            recommended_action = "Review the cited records and reconcile the issue before using this export in demand or mediation."
        else:
            title, attorney_message, defense_risk, recommended_action = template
        if code == "MECHANISM_OR_DIAGNOSIS_UNSUPPORTED":
            extra = format_claim_alignment_failure_summary(f.get("claim_failures"))
            if extra:
                attorney_message = f"{attorney_message} {extra}"
        out.append(
            {
                "code": code,
                "display_title": title,
                "attorney_message": attorney_message,
                "defense_risk": defense_risk,
                "recommended_action": recommended_action,
            }
        )
    return out
