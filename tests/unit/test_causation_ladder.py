from __future__ import annotations

from apps.worker.lib.causation_ladder import build_causation_ladders


def test_build_causation_ladders_basic_chain() -> None:
    rows = [
        {
            "id": "1",
            "event_id": "e1",
            "claim_type": "SYMPTOM",
            "date": "2025-04-04",
            "body_region": "lumbar",
            "assertion": "Patient presents after rear-end MVA with low back pain.",
            "citations": ["packet.pdf p. 3"],
            "support_score": 3,
        },
        {
            "id": "2",
            "event_id": "e2",
            "claim_type": "INJURY_DX",
            "date": "2025-04-11",
            "body_region": "lumbar",
            "assertion": "Assessment: lumbar strain.",
            "citations": ["packet.pdf p. 8"],
            "support_score": 4,
        },
        {
            "id": "3",
            "event_id": "e3",
            "claim_type": "TREATMENT_VISIT",
            "date": "2025-04-18",
            "body_region": "lumbar",
            "assertion": "PT follow-up with ROM and strength measurements.",
            "citations": ["packet.pdf p. 14"],
            "support_score": 3,
        },
        {
            "id": "4",
            "event_id": "e4",
            "claim_type": "PROCEDURE",
            "date": "2025-06-10",
            "body_region": "lumbar",
            "assertion": "Epidural injection performed.",
            "citations": ["packet.pdf p. 56"],
            "support_score": 5,
        },
        {
            "id": "5",
            "event_id": "e5",
            "claim_type": "SYMPTOM",
            "date": "2025-07-20",
            "body_region": "lumbar",
            "assertion": "Discharge summary final pain 2/10.",
            "citations": ["packet.pdf p. 78"],
            "support_score": 3,
        },
    ]
    chains = build_causation_ladders(rows)
    assert chains
    lumbar = chains[0]
    assert lumbar["body_region"] == "lumbar"
    rung_types = [r["rung_type"] for r in lumbar["rungs"]]
    assert "INCIDENT" in rung_types
    assert "INITIAL_DX" in rung_types
    assert "TREATMENT" in rung_types
    assert "ESCALATION" in rung_types
    assert "OUTCOME" in rung_types
    assert isinstance(lumbar["chain_integrity_score"], int)


def test_causation_ladder_marks_missing_rungs() -> None:
    rows = [
        {
            "id": "a1",
            "event_id": "e1",
            "claim_type": "INJURY_DX",
            "date": "2025-01-01",
            "body_region": "cervical",
            "assertion": "Diagnosis: cervical strain.",
            "citations": ["packet.pdf p. 3"],
            "support_score": 3,
        }
    ]
    chains = build_causation_ladders(rows)
    assert chains
    missing = set(chains[0]["missing_rungs"])
    assert "INCIDENT" in missing
    assert "ESCALATION" in missing


def test_causation_ladder_applies_temporal_decay_and_provider_weighting() -> None:
    rows = [
        {
            "id": "z1",
            "event_id": "e1",
            "claim_type": "SYMPTOM",
            "date": "2021-01-01",
            "body_region": "cervical",
            "provider": "Emergency Department",
            "assertion": "Chief complaint after MVC with neck pain.",
            "citations": ["packet.pdf p. 1"],
            "support_score": 4,
        },
        {
            "id": "z2",
            "event_id": "e2",
            "claim_type": "TREATMENT_VISIT",
            "date": "2024-05-01",
            "body_region": "cervical",
            "provider": "Chiropractic Clinic",
            "assertion": "Follow-up visit with continued neck pain.",
            "citations": ["packet.pdf p. 80"],
            "support_score": 3,
        },
    ]
    chains = build_causation_ladders(rows)
    assert chains
    chain = chains[0]
    assert int(chain.get("temporal_decay_penalty", 0)) >= 1
    assert float(chain.get("provider_reliability_multiplier_avg", 1.0)) < 1.0
