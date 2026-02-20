from __future__ import annotations

from apps.worker.steps.litigation import build_narrative_duality


def test_narrative_duality_returns_both_sides() -> None:
    rows = [
        {
            "id": "1",
            "event_id": "e1",
            "claim_type": "IMAGING_FINDING",
            "date": "2025-04-01",
            "assertion": "MRI impression shows C5-6 protrusion.",
            "support_strength": "Strong",
            "support_score": 7,
            "citations": ["packet.pdf p. 10"],
            "citation": "packet.pdf p. 10",
            "flags": [],
        },
        {
            "id": "2",
            "event_id": "e2",
            "claim_type": "GAP_IN_CARE",
            "date": "2025-09-01",
            "assertion": "Treatment gap of 120 days identified.",
            "support_strength": "Medium",
            "support_score": 5,
            "citations": ["packet.pdf p. 22"],
            "citation": "packet.pdf p. 22",
            "flags": ["treatment_gap"],
        },
        {
            "id": "3",
            "event_id": "e3",
            "claim_type": "PRE_EXISTING_MENTION",
            "date": "2024-12-01",
            "assertion": "History of chronic neck pain before incident.",
            "support_strength": "Medium",
            "support_score": 5,
            "citations": ["packet.pdf p. 3"],
            "citation": "packet.pdf p. 3",
            "flags": ["pre_existing_overlap"],
        },
    ]
    dual = build_narrative_duality(rows)
    assert "plaintiff_narrative" in dual
    assert "defense_narrative" in dual
    assert isinstance((dual["plaintiff_narrative"] or {}).get("points"), list)
    assert isinstance((dual["defense_narrative"] or {}).get("points"), list)

