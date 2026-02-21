from __future__ import annotations

import re
from typing import Any


HIGH_RISK_FIELDS = {"primary injuries", "major complications"}
INSUFFICIENT_ANCHOR_MSG = "Insufficiently anchored in record text; additional records or citations required."


def _split_claim_values(value: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[;,]", value or "") if p.strip()]
    return parts


def _anchor_pages_for_claim(claim_value: str, page_text_by_number: dict[int, str] | None) -> list[int]:
    if not claim_value or not page_text_by_number:
        return []
    token = re.escape(claim_value.strip().lower())
    pages: list[int] = []
    for page_num in sorted(page_text_by_number.keys()):
        text = (page_text_by_number.get(page_num) or "").lower()
        if re.search(rf"\b{token}\b", text):
            pages.append(page_num)
    return pages


def guard_high_risk_claims(
    candidate_claims: list[dict[str, Any]],
    page_text_by_number: dict[int, str] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for claim in candidate_claims:
        ctype = str(claim.get("type") or "").strip().lower()
        cval = str(claim.get("value") or "").strip()
        anchors = list(dict.fromkeys(_anchor_pages_for_claim(cval, page_text_by_number)))
        payload = {"type": ctype, "value": cval, "anchors": anchors}
        if ctype in HIGH_RISK_FIELDS and len(anchors) < 2:
            payload["reason"] = "HIGH_RISK_UNANCHORED"
            rejected.append(payload)
        else:
            accepted.append(payload)
    return accepted, rejected


def apply_claim_guard_to_narrative(
    narrative: str | None,
    page_text_by_number: dict[int, str] | None,
) -> tuple[str | None, dict[str, Any]]:
    if not narrative:
        return narrative, {"accepted_claims": [], "rejected_claims": []}

    lines = narrative.splitlines()
    accepted_all: list[dict[str, Any]] = []
    rejected_all: list[dict[str, Any]] = []
    out_lines: list[str] = []
    rejected_terms: set[str] = set()

    for line in lines:
        m = re.match(r"^\s*([^:]+)\s*:\s*(.*)$", line)
        if not m:
            out_lines.append(line)
            continue
        field = m.group(1).strip().lower()
        value = m.group(2).strip()
        if field not in HIGH_RISK_FIELDS:
            out_lines.append(line)
            continue

        claims = [{"type": field, "value": part} for part in _split_claim_values(value)]
        accepted, rejected = guard_high_risk_claims(claims, page_text_by_number)
        accepted_all.extend(accepted)
        rejected_all.extend(rejected)
        for r in rejected:
            rv = str(r.get("value") or "").strip().lower()
            if rv:
                rejected_terms.add(rv)
        if accepted:
            out_lines.append(f"{m.group(1).strip()}: {', '.join(c['value'] for c in accepted)}")
        else:
            out_lines.append(f"{m.group(1).strip()}: {INSUFFICIENT_ANCHOR_MSG}")

    # Global scrub: rejected high-risk claim terms must not leak into rendered narrative sections.
    scrubbed_lines: list[str] = []
    for line in out_lines:
        low = line.lower()
        if any(term in low for term in rejected_terms):
            # Keep section headers but clear rejected content.
            if re.match(r"^\s*[-*]\s*", line):
                continue
            m = re.match(r"^\s*([^:]+)\s*:\s*(.*)$", line)
            if m:
                scrubbed_lines.append(f"{m.group(1).strip()}: {INSUFFICIENT_ANCHOR_MSG}")
            else:
                continue
        else:
            scrubbed_lines.append(line)

    return "\n".join(scrubbed_lines), {"accepted_claims": accepted_all, "rejected_claims": rejected_all}
