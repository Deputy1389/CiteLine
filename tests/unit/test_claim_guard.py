from __future__ import annotations

from apps.worker.lib.claim_guard import apply_claim_guard_to_narrative


def test_unanchored_high_risk_claim_suppressed():
    narrative = "\n".join(
        [
            "### 1) CASE SUMMARY",
            "Date of Injury: Not established from records",
            "Primary Injuries: Wound infection",
            "Major Complications: Wound infection",
            "### 2) INJURY SUMMARY",
            "- Wound infection",
        ]
    )
    page_text = {
        1: "ED note discussing neck strain.",
        2: "Physical therapy intake and lumbar pain.",
    }
    cleaned, report = apply_claim_guard_to_narrative(narrative, page_text)
    assert cleaned is not None
    assert "Primary Injuries: Not stated in records" in cleaned
    assert "Major Complications: Not stated in records" in cleaned
    assert "Wound infection" not in cleaned
    rejected = report.get("rejected_claims", [])
    assert rejected
    assert any(r.get("reason") == "HIGH_RISK_UNANCHORED" for r in rejected)
