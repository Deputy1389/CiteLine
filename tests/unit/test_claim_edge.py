from __future__ import annotations

from packages.shared.models import ClaimEdge, LitigationExtensions


def test_claim_edge_round_trip_preserves_json_shape() -> None:
    payload = {
        "id": "c1",
        "event_id": "e1",
        "patient_label": "P1",
        "claim_type": "INJURY_DX",
        "date": "2025-01-01",
        "body_region": "lumbar",
        "provider": "Dr. Smith",
        "assertion": "Assessment: lumbar strain after MVC.",
        "citations": ["packet.pdf p. 10"],
        "support_score": 5,
        "support_strength": "Medium",
        "flags": [],
        "materiality_weight": 2,
        "selection_score": 10,
    }
    edge = ClaimEdge.model_validate(payload)
    assert edge.model_dump(mode="json") == payload


def test_claim_edge_allows_and_preserves_extra_fields_during_migration() -> None:
    payload = {
        "id": "c2",
        "event_id": "e2",
        "patient_label": "P1",
        "claim_type": "GAP_IN_CARE",
        "date": "2025-03-01",
        "body_region": "general",
        "provider": "Unknown",
        "assertion": "Treatment gap of 90 days identified.",
        "citations": ["packet.pdf p. 20"],
        "support_score": 5,
        "support_strength": "Medium",
        "flags": ["treatment_gap"],
        "materiality_weight": 2,
        "selection_score": 10,
        "citation": "packet.pdf p. 20",
        "bucket": "gap",
        "score": 10,
    }
    edge = ClaimEdge.model_validate(payload)
    dumped = edge.model_dump(mode="json")
    assert dumped["citation"] == "packet.pdf p. 20"
    assert dumped["bucket"] == "gap"
    assert dumped["score"] == 10
    assert edge.get("citation") == "packet.pdf p. 20"
    assert edge.get("unknown_key", "fallback") == "fallback"


def test_litigation_extensions_accepts_dict_payloads() -> None:
    payload = {
        "claim_rows": [
            {
                "id": "c1",
                "event_id": "e1",
                "patient_label": "P1",
                "claim_type": "INJURY_DX",
                "date": "2025-01-01",
                "body_region": "lumbar",
                "provider": "Dr. Smith",
                "assertion": "Assessment: lumbar strain after MVC.",
                "citations": ["packet.pdf p. 10"],
                "support_score": 5,
                "support_strength": "Medium",
                "flags": [],
                "materiality_weight": 2,
                "selection_score": 10,
            }
        ]
    }
    ext = LitigationExtensions.model_validate(payload)
    dumped = ext.model_dump(mode="json")
    assert dumped["claim_rows"][0]["id"] == "c1"

