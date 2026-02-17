from __future__ import annotations

from datetime import date

from apps.worker.lib.provider_normalize import normalize_provider_entities
from apps.worker.steps.events.legal_usability import improve_legal_usability
from apps.worker.steps.step15_missing_records import detect_missing_records
from packages.shared.models import (
    DateKind,
    DateSource,
    EvidenceGraph,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Provider,
    ProviderType,
)


def _evt(event_id: str, provider_id: str, day: int, fact_text: str = "note") -> Event:
    return Event(
        event_id=event_id,
        provider_id=provider_id,
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=date(2024, 1, day), source=DateSource.TIER1),
        facts=[Fact(text=fact_text, kind=FactKind.OTHER, verbatim=True, citation_id="c1")],
        confidence=80,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[1],
    )


def _graph() -> EvidenceGraph:
    return EvidenceGraph(
        providers=[
            Provider(
                provider_id="p1",
                detected_name_raw="LSU Public Hospital",
                normalized_name="lsu public hospital",
                provider_type=ProviderType.HOSPITAL,
                confidence=95,
            )
        ],
        events=[
            _evt("e1", "p1", 1),
            _evt("e2", "p1", 15),
            _evt("e3", "p1", 28),
        ],
    )


def test_non_filtering_stage_event_count_invariant():
    graph = _graph()
    before = len(graph.events)

    normalized_events = improve_legal_usability(list(graph.events))
    assert len(normalized_events) >= before

    graph.events = normalized_events
    before_provider_norm = len(graph.events)
    _ = normalize_provider_entities(graph)
    assert len(graph.events) >= before_provider_norm

    before_missing_detection = len(graph.events)
    _ = detect_missing_records(graph, [])
    assert len(graph.events) >= before_missing_detection
