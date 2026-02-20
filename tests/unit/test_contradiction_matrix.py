from __future__ import annotations

from apps.worker.steps.litigation import build_contradiction_matrix


def _row(
    *,
    rid: str,
    date: str,
    claim_type: str,
    assertion: str,
    support_score: int = 4,
    citations: list[str] | None = None,
) -> dict:
    return {
        "id": rid,
        "event_id": rid,
        "date": date,
        "claim_type": claim_type,
        "assertion": assertion,
        "support_score": support_score,
        "citations": citations or ["packet.pdf p. 1"],
    }


def test_contradiction_matrix_detects_laterality_conflict() -> None:
    rows = [
        _row(rid="a", date="2025-01-01", claim_type="SYMPTOM", assertion="Patient reports left leg numbness."),
        _row(rid="b", date="2025-01-10", claim_type="SYMPTOM", assertion="Patient reports right leg numbness."),
    ]
    matrix = build_contradiction_matrix(rows, window_days=30)
    assert matrix
    assert any(r.get("category") == "laterality" for r in matrix)


def test_contradiction_matrix_detects_pain_delta() -> None:
    rows = [
        _row(rid="a", date="2025-01-01", claim_type="SYMPTOM", assertion="Pain 8/10."),
        _row(rid="b", date="2025-01-08", claim_type="SYMPTOM", assertion="Pain 3/10."),
    ]
    matrix = build_contradiction_matrix(rows, window_days=30)
    assert any(r.get("category") == "pain_severity" for r in matrix)

