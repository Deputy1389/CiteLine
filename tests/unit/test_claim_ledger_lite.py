from __future__ import annotations

from apps.worker.lib.claim_ledger_lite import (
    build_claim_ledger_lite,
    depo_safe_rewrite,
    select_top_claim_rows,
)
from apps.worker.project.models import ChronologyProjectionEntry


def _entry(
    event_id: str,
    date_display: str,
    event_type_display: str,
    facts: list[str],
    citation_display: str = "packet.pdf p. 5",
    patient_label: str = "See Patient Header",
) -> ChronologyProjectionEntry:
    return ChronologyProjectionEntry(
        event_id=event_id,
        date_display=date_display,
        provider_display="Elite Physical Therapy",
        event_type_display=event_type_display,
        patient_label=patient_label,
        facts=facts,
        citation_display=citation_display,
        confidence=85,
    )


def test_build_claim_ledger_extracts_diagnosis_like_rows():
    entries = [
        _entry(
            "e1",
            "2025-04-07 (time not documented)",
            "Therapy Visit",
            [
                "Assessment: cervical strain with neck pain after rear-end MVC.",
                "Plan: continue PT and reassess ROM.",
            ],
        )
    ]
    rows = build_claim_ledger_lite(entries)
    dx_rows = [r for r in rows if r["claim_type"] == "INJURY_DX"]
    assert len(dx_rows) >= 1


def test_depo_safe_rewrite_blocks_unsupported_causation_and_permanency():
    sentence = "Symptoms were caused by the crash and are permanent."
    safe = depo_safe_rewrite(sentence, claim_rows=[])
    assert "caused by" not in safe.lower()
    assert "permanent" not in safe.lower()


def test_depo_safe_rewrite_preserves_supported_causation():
    sentence = "Symptoms were caused by the crash."
    claim_rows = [
        {
            "assertion": "Provider assessment states symptoms are caused by the crash.",
            "claim_type": "INJURY_DX",
            "flags": [],
        }
    ]
    safe = depo_safe_rewrite(sentence, claim_rows=claim_rows)
    assert "caused by" in safe.lower()


def test_select_top_claim_rows_filters_noise_and_requires_citations():
    rows = [
        {
            "id": "1",
            "claim_type": "SYMPTOM",
            "assertion": "Born water town wear particular power.",
            "citations": ["packet.pdf p. 3"],
            "selection_score": 10,
            "date": "2025-01-01",
        },
        {
            "id": "2",
            "claim_type": "IMAGING_FINDING",
            "assertion": "MRI impression shows C5-6 disc protrusion and foraminal narrowing.",
            "citations": ["packet.pdf p. 40"],
            "selection_score": 21,
            "date": "2025-02-01",
        },
        {
            "id": "3",
            "claim_type": "TREATMENT_VISIT",
            "assertion": "Routine follow-up.",
            "citations": [],
            "selection_score": 15,
            "date": "2025-03-01",
        },
    ]
    top = select_top_claim_rows(rows, limit=10)
    assert len(top) == 1
    assert top[0]["claim_type"] == "IMAGING_FINDING"


def test_select_top_claim_rows_filters_irrelevant_dx_noise():
    rows = [
        {
            "id": "dx1",
            "claim_type": "INJURY_DX",
            "assertion": "Pain Assessment: action result high consumer water office race boy.",
            "citations": ["packet.pdf p. 12"],
            "selection_score": 20,
            "support_score": 5,
            "date": "2025-04-14",
        },
        {
            "id": "dx2",
            "claim_type": "INJURY_DX",
            "assertion": "Assessment: cervical strain with neck pain after rear-end MVC.",
            "citations": ["packet.pdf p. 14"],
            "selection_score": 12,
            "support_score": 5,
            "date": "2025-04-14",
        },
    ]
    top = select_top_claim_rows(rows, limit=10)
    assert len(top) == 1
    assert "cervical strain" in top[0]["assertion"].lower()


def test_select_top_claim_rows_prefers_high_impact_buckets():
    rows = [
        {
            "id": "sym1",
            "claim_type": "SYMPTOM",
            "assertion": "Subjective: neck pain 6/10 after MVA.",
            "citations": ["packet.pdf p. 10"],
            "selection_score": 8,
            "support_score": 2,
            "date": "2025-04-11",
        },
        {
            "id": "img1",
            "claim_type": "IMAGING_FINDING",
            "assertion": "MRI impression: C5-6 disc protrusion with foraminal narrowing.",
            "citations": ["packet.pdf p. 40"],
            "selection_score": 21,
            "support_score": 7,
            "date": "2025-05-08",
        },
        {
            "id": "pro1",
            "claim_type": "PROCEDURE",
            "assertion": "Epidural steroid injection performed with fluoroscopy guidance.",
            "citations": ["packet.pdf p. 101"],
            "selection_score": 18,
            "support_score": 6,
            "date": "2025-06-10",
        },
    ]
    top = select_top_claim_rows(rows, limit=2)
    types = {r["claim_type"] for r in top}
    assert "IMAGING_FINDING" in types
    assert "PROCEDURE" in types


def test_select_top_claim_rows_dedupes_same_render_key():
    rows = [
        {
            "id": "pro1",
            "claim_type": "PROCEDURE",
            "assertion": "Epidural steroid injection performed with fluoroscopy guidance.",
            "citations": ["packet.pdf p. 66", "packet.pdf p. 67"],
            "selection_score": 19,
            "support_score": 6,
            "date": "2025-08-11",
        },
        {
            "id": "pro2",
            "claim_type": "PROCEDURE",
            "assertion": "Cervical disc displacement with radiculopathy documented.",
            "citations": ["packet.pdf p. 66", "packet.pdf p. 67"],
            "selection_score": 18,
            "support_score": 5,
            "date": "2025-08-11",
        },
        {
            "id": "img1",
            "claim_type": "IMAGING_FINDING",
            "assertion": "MRI impression: C5-6 disc protrusion.",
            "citations": ["packet.pdf p. 145"],
            "selection_score": 21,
            "support_score": 7,
            "date": "2025-09-13",
        },
    ]
    top = select_top_claim_rows(rows, limit=10)
    procedure_rows = [r for r in top if r["claim_type"] == "PROCEDURE" and r["date"] == "2025-08-11"]
    assert len(procedure_rows) == 1
