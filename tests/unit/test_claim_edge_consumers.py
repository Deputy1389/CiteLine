from __future__ import annotations

from apps.worker.lib.causation_ladder import build_causation_ladders
from apps.worker.steps.case_collapse import build_case_collapse_candidates
from apps.worker.steps.litigation import build_contradiction_matrix, build_narrative_duality
from packages.shared.models import ClaimEdge


def _rows() -> list[ClaimEdge]:
    return [
        ClaimEdge(
            id="c1",
            event_id="e1",
            patient_label="P1",
            claim_type="INJURY_DX",
            date="2025-01-01",
            body_region="cervical",
            provider="ER",
            assertion="Rear-end MVC with cervical strain and neck pain 8/10.",
            citations=["packet.pdf p. 1", "packet.pdf p. 2"],
            support_score=6,
            support_strength="Strong",
            flags=[],
            materiality_weight=2,
            selection_score=12,
        ),
        ClaimEdge(
            id="c2",
            event_id="e2",
            patient_label="P1",
            claim_type="SYMPTOM",
            date="2025-01-10",
            body_region="cervical",
            provider="PT",
            assertion="Neck pain improved to 3/10 and returned to work full duty.",
            citations=["packet.pdf p. 5"],
            support_score=3,
            support_strength="Medium",
            flags=[],
            materiality_weight=1,
            selection_score=3,
        ),
        ClaimEdge(
            id="c3",
            event_id="e3",
            patient_label="P1",
            claim_type="GAP_IN_CARE",
            date="2025-03-15",
            body_region="general",
            provider="Unknown",
            assertion="Treatment gap of 70 days identified.",
            citations=["packet.pdf p. 9", "packet.pdf p. 10"],
            support_score=5,
            support_strength="Medium",
            flags=["treatment_gap"],
            materiality_weight=2,
            selection_score=10,
        ),
        ClaimEdge(
            id="c4",
            event_id="e4",
            patient_label="P1",
            claim_type="PRE_EXISTING_MENTION",
            date="2024-12-01",
            body_region="cervical",
            provider="PCP",
            assertion="History of chronic neck pain prior to incident.",
            citations=["packet.pdf p. 11", "packet.pdf p. 12"],
            support_score=4,
            support_strength="Medium",
            flags=["pre_existing_overlap"],
            materiality_weight=1,
            selection_score=4,
        ),
    ]


def test_consumers_accept_claim_edge_objects() -> None:
    rows = _rows()
    collapse = build_case_collapse_candidates(rows)
    ladders = build_causation_ladders(rows)
    matrix = build_contradiction_matrix(rows, window_days=90)
    duality = build_narrative_duality(rows)

    assert isinstance(collapse, list)
    assert isinstance(ladders, list)
    assert isinstance(matrix, list)
    assert isinstance(duality, dict)

