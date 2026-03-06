from __future__ import annotations

from apps.worker.lib.litigation_review import LitigationReviewer


def test_q2_passes_compact_packet_when_evidence_is_sufficient() -> None:
    reviewer = LitigationReviewer("run-compact")
    reviewer.load_from_memory(
        events=[
            {
                "id": "evt-1",
                "event_type": "hospital_admission",
                "citation_ids": ["cit-1", "cit-2", "cit-3"],
                "date": {"value": "2180-05-06T22:23:00+00:00"},
            }
        ],
        text_content="ADMITTED 2180-05-06 PRIMARY DIAGNOSIS Sodium 144 Potassium 3.5 Creatinine 0.84",
        extensions={
            "citation_fidelity": {
                "claim_rows_anchored": 1,
                "claim_rows_text_backed": 1,
                "drift_review_required": False,
            },
            "extraction_metrics": {
                "citations_total": 21,
            },
        },
    )

    checklist = reviewer.run_checks()

    assert checklist["quality_gates"]["Q2"]["pass"] is True
    assert checklist["pass"] is True


def test_q10_fails_when_citation_drift_is_detected() -> None:
    reviewer = LitigationReviewer("run-drift")
    reviewer.load_from_memory(
        events=[
            {
                "id": "evt-1",
                "event_type": "hospital_admission",
                "citation_ids": ["cit-1"],
                "date": {"value": "2024-01-01T00:00:00+00:00"},
            }
        ],
        text_content="Patient denies chest pain.",
        extensions={
            "citation_fidelity": {
                "claim_rows_anchored": 1,
                "claim_rows_text_backed": 0,
                "drift_review_required": True,
                "drift_suspects": [{"id": "claim-1", "best_overlap": 0.0}],
            },
            "extraction_metrics": {
                "citations_total": 4,
            },
        },
    )

    checklist = reviewer.run_checks()

    assert checklist["quality_gates"]["Q10"]["pass"] is False
    assert checklist["quality_gates"]["Q10"]["details"]
    assert checklist["pass"] is False
