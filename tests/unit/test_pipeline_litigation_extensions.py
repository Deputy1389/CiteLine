from __future__ import annotations

from apps.worker.pipeline import _build_litigation_extensions


def test_build_litigation_extensions_contract() -> None:
    claim_rows = [
        {
            "id": "c1",
            "event_id": "e1",
            "patient_label": "P1",
            "claim_type": "PRE_EXISTING_MENTION",
            "date": "2024-01-01",
            "body_region": "lumbar",
            "provider": "Unknown",
            "assertion": "History of chronic lumbar pain prior to incident.",
            "citations": ["packet.pdf p. 5", "packet.pdf p. 6"],
            "support_score": 4,
            "support_strength": "Medium",
            "flags": ["pre_existing_overlap"],
            "materiality_weight": 1,
            "selection_score": 4,
            "citation": "packet.pdf p. 5 | packet.pdf p. 6",
            "bucket": "diagnosis",
            "score": 4,
        },
        {
            "id": "c2",
            "event_id": "e2",
            "patient_label": "P1",
            "claim_type": "GAP_IN_CARE",
            "date": "2024-03-01",
            "body_region": "general",
            "provider": "Unknown",
            "assertion": "Treatment gap of 120 days identified.",
            "citations": ["packet.pdf p. 20", "packet.pdf p. 21"],
            "support_score": 5,
            "support_strength": "Medium",
            "flags": ["treatment_gap"],
            "materiality_weight": 2,
            "selection_score": 10,
            "citation": "packet.pdf p. 20 | packet.pdf p. 21",
            "bucket": "gap",
            "score": 10,
        },
    ]
    ext = _build_litigation_extensions(claim_rows)
    assert "claim_rows" in ext
    assert "causation_chains" in ext
    assert "citation_fidelity" in ext
    assert "case_collapse_candidates" in ext
    assert "defense_attack_paths" in ext
    assert "objection_profiles" in ext
    assert "evidence_upgrade_recommendations" in ext
    assert "quote_lock_rows" in ext
    assert "contradiction_matrix" in ext
    assert "narrative_duality" in ext
    assert "comparative_pattern_engine" in ext
    assert isinstance(ext["quote_lock_rows"], list)
    if ext["quote_lock_rows"]:
        assert all("quote" in q for q in ext["quote_lock_rows"])
