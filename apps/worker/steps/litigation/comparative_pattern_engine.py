from __future__ import annotations

from collections import Counter


def build_comparative_pattern_snapshot(claim_rows: list[dict]) -> dict:
    """
    Comparative Pattern Engine scaffold.
    Deterministic snapshot only; no cross-case claims until corpus baseline is available.
    """
    by_type = Counter(str(r.get("claim_type") or "UNKNOWN") for r in claim_rows)
    avg_support = round(
        (sum(int(r.get("support_score") or 0) for r in claim_rows) / max(1, len(claim_rows))),
        2,
    )
    return {
        "status": "insufficient_corpus_for_comparative_deviation",
        "version": "v0_scaffold",
        "required_min_cases": 500,
        "current_case_features": {
            "claim_row_count": len(claim_rows),
            "claim_type_distribution": dict(sorted(by_type.items())),
            "avg_support_score": avg_support,
        },
        "deviation_flags": [],
    }

