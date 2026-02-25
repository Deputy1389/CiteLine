from datetime import date

from apps.worker.steps.step_renderer_manifest import build_renderer_manifest
from packages.shared.models import (
    DateKind,
    DateSource,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
)


def _pt_event(event_id: str, start: date, end: date, fact_text: str, citation_ids: list[str] | None = None) -> Event:
    return Event(
        event_id=event_id,
        provider_id="prov-pt",
        event_type=EventType.PT_VISIT,
        date=EventDate(kind=DateKind.RANGE, value={"start": start, "end": end}, source=DateSource.TIER1),
        facts=[Fact(text=fact_text, kind=FactKind.OTHER, verbatim=True, citation_ids=citation_ids or [])],
        confidence=85,
        citation_ids=citation_ids or [],
        source_page_numbers=[52],
    )


def test_renderer_manifest_prefers_aggregate_pt_count_and_sanitizes_dates() -> None:
    events = [
        _pt_event("pt-1", date(1900, 1, 1), date(1900, 1, 1), "PT sessions documented: 117", ["c1"]),
        _pt_event("pt-2", date(2024, 10, 17), date(2025, 11, 13), "Aggregated PT sessions (117 encounters)", ["c2"]),
    ]
    manifest = build_renderer_manifest(events=events, evidence_graph_extensions={}, specials_summary=None)
    assert manifest.pt_summary.total_encounters == 117
    assert manifest.pt_summary.count_source == "aggregate_snippet"
    assert manifest.pt_summary.date_start == "2024-10-17"
    assert manifest.pt_summary.date_end == "2025-11-13"


def test_renderer_manifest_promotes_claim_rows_with_priority_categories() -> None:
    claim_rows = [
        {
            "event_id": "e1",
            "claim_type": "INJURY_DX",
            "assertion": "Cervical disc displacement with radiculopathy",
            "citations": ["packet.pdf p. 101"],
            "selection_score": 90,
        },
        {
            "event_id": "e2",
            "claim_type": "IMAGING_FINDING",
            "assertion": "Unremarkable lumbar spine series",
            "citations": ["packet.pdf p. 88"],
            "selection_score": 92,
            "flags": ["degenerative_language"],
        },
        {
            "event_id": "e3",
            "claim_type": "PROCEDURE",
            "assertion": "Cervical epidural steroid injection performed",
            "citations": ["packet.pdf p. 140"],
            "selection_score": 85,
        },
        {
            "event_id": "e4",
            "claim_type": "SYMPTOM",
            "assertion": "Weakness 4/5 documented",
            "citations": ["packet.pdf p. 100"],
            "selection_score": 80,
        },
    ]
    manifest = build_renderer_manifest(
        events=[],
        evidence_graph_extensions={"claim_rows": claim_rows},
        specials_summary={"flags": ["PARTIAL_BILLING_ONLY"], "by_provider": [{"provider_display_name": "PT", "charges": 100}]},
    )
    categories = [f.category for f in manifest.promoted_findings]
    assert "objective_deficit" in categories
    assert "diagnosis" in categories
    assert "procedure" in categories
    low_img = next(f for f in manifest.promoted_findings if "Unremarkable lumbar spine series" in f.label)
    assert low_img.headline_eligible is False
    assert low_img.finding_polarity == "negative"
    assert manifest.billing_completeness == "partial"
    assert manifest.top_case_drivers
