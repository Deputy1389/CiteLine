from datetime import date

from apps.worker.steps.step_renderer_manifest import build_renderer_manifest
from packages.shared.models import (
    BBox,
    Citation,
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


def test_renderer_manifest_pt_conflict_adds_reconciliation_note() -> None:
    events = [
        _pt_event("pt-1", date(2024, 10, 17), date(2025, 11, 13), "PT sessions documented: 117", ["c1"]),
        _pt_event("pt-2", date(2024, 10, 20), date(2025, 11, 13), "Aggregated PT sessions (141 encounters)", ["c2"]),
    ]
    manifest = build_renderer_manifest(events=events, evidence_graph_extensions={}, specials_summary=None)
    assert manifest.pt_summary.total_encounters == 141
    assert manifest.pt_summary.encounter_count_min == 117
    assert manifest.pt_summary.encounter_count_max == 141
    assert manifest.pt_summary.reconciliation_note


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


def test_renderer_manifest_extracts_mechanism_from_cited_event_text() -> None:
    evt = Event(
        event_id="er-1",
        provider_id="prov-er",
        event_type=EventType.ER_VISIT,
        reason_for_visit="Rear-end MVC with neck and back pain",
        facts=[Fact(text="Patient presents after rear-end motor vehicle collision", kind=FactKind.OTHER, verbatim=True, citation_ids=["c-mvc"])],
        confidence=90,
        citation_ids=["c-mvc"],
    )
    manifest = build_renderer_manifest(events=[evt], evidence_graph_extensions={}, specials_summary=None)
    assert manifest.mechanism.value == "rear-end motor vehicle collision"
    assert "c-mvc" in manifest.mechanism.citation_ids


def test_renderer_manifest_falls_back_to_citation_snippets_for_mechanism_dx_and_pt_count() -> None:
    citations = [
        Citation(citation_id="c1", source_document_id="doc-1", page_number=11, snippet="Rear-end motor vehicle collision", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="c2", source_document_id="doc-1", page_number=23, snippet="Aggregated PT sessions (141 encounters) (ROM, Exercise, Gait, Strength).", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="c3", source_document_id="doc-1", page_number=112, snippet="1. Cervical Disc Displacement (ICD-10 M50.20) with Radiculopathy (M54.12)", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="c4", source_document_id="doc-1", page_number=108, snippet="The MRI shows significant disc material extending into the neural foramen on the left side at the C5-C6 level.", bbox=BBox(x=1, y=1, w=1, h=1)),
    ]
    # One PT event with low aggregate in event facts to ensure citation fallback can elevate max.
    events = [_pt_event("pt-1", date(2024, 10, 17), date(2025, 11, 13), "PT sessions documented: 117", ["ept1"])]
    manifest = build_renderer_manifest(events=events, evidence_graph_extensions={}, specials_summary=None, citations=citations)
    assert manifest.mechanism.value == "rear-end motor vehicle collision"
    assert manifest.pt_summary.total_encounters == 141
    cats = [f.category for f in manifest.promoted_findings]
    assert "diagnosis" in cats
    assert "imaging" in cats
