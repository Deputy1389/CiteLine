from __future__ import annotations

from apps.worker.lib.citation_fidelity import assess_claim_row_fidelity
from packages.shared.models import BBox, Citation


def test_assess_claim_row_fidelity_flags_drift_when_overlap_is_missing() -> None:
    claim_rows = [
        {
            "id": "claim-1",
            "event_id": "evt-1",
            "claim_type": "SYMPTOM",
            "assertion": "Patient presented with chest pain.",
            "citation_ids": ["cit-1"],
            "citations": ["packet.pdf p. 4"],
        }
    ]
    citations = [
        Citation(
            citation_id="cit-1",
            source_document_id="doc-1",
            page_number=4,
            snippet="Patient denies chest pain.",
            bbox=BBox(x=0, y=0, w=1, h=1),
        )
    ]

    fidelity = assess_claim_row_fidelity(claim_rows, citations)

    assert fidelity["claim_rows_anchored"] == 1
    assert fidelity["claim_rows_text_backed"] == 0
    assert fidelity["drift_review_required"] is True
    assert fidelity["drift_suspect_count"] == 1
