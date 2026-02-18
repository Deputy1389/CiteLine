from __future__ import annotations

from datetime import date

from apps.worker.steps.events.event_weighting import annotate_event_weights
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
)


def _evt(eid: str, d: date, scope: str, text: str = "office follow up", event_type: EventType = EventType.OFFICE_VISIT) -> Event:
    return Event(
        event_id=eid,
        provider_id="p1",
        event_type=event_type,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1),
        facts=[Fact(text=text, kind=FactKind.OTHER, verbatim=True)],
        confidence=80,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[1],
        extensions={"patient_scope_id": scope},
    )


def test_global_gaps_do_not_cross_patient_scope():
    # Same dates across two patients should not produce cross-patient global gaps.
    events = [
        _evt("a1", date(2024, 1, 1), "ps_a"),
        _evt("a2", date(2024, 3, 1), "ps_a"),
        _evt("b1", date(2024, 1, 15), "ps_b"),
        _evt("b2", date(2024, 2, 15), "ps_b"),
    ]
    annotate_event_weights(events)
    graph = EvidenceGraph(events=events)
    result = detect_missing_records(graph, [])
    global_gaps = [g for g in result["gaps"] if g["rule_name"] == "global_gap"]
    assert all(g["patient_scope_id"] in {"ps_a", "ps_b"} for g in global_gaps)
    # ps_b gap is 31 days and should not qualify as global gap; ps_a gap is 60 and should.
    assert any(g["patient_scope_id"] == "ps_a" and g["gap_days"] == 60 for g in global_gaps)
    assert not any(g["patient_scope_id"] == "ps_b" for g in global_gaps)


def test_vitals_only_events_are_excluded_from_gap_computation():
    events = [
        _evt("e1", date(2024, 1, 1), "ps_a", text="Body height, body weight, blood pressure, heart rate"),
        _evt("e2", date(2024, 5, 1), "ps_a", text="Body height, body weight, blood pressure, heart rate"),
    ]
    annotate_event_weights(events)
    graph = EvidenceGraph(events=events)
    result = detect_missing_records(graph, [])
    assert result["gaps"] == []
