from __future__ import annotations

from datetime import date

from apps.worker.steps.step15_missing_records import detect_missing_records
from packages.shared.models import DateKind, DateSource, EvidenceGraph, Event, EventDate, EventType, Fact, FactKind


def _evt(eid: str, d: date, scope: str) -> Event:
    return Event(
        event_id=eid,
        provider_id="p1",
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1),
        facts=[Fact(text="follow up diagnosis noted", kind=FactKind.OTHER, verbatim=True)],
        confidence=80,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[1],
        extensions={"patient_scope_id": scope},
    )


def test_unknown_scope_excluded_from_gap_computation():
    graph = EvidenceGraph(
        events=[
            _evt("known-1", date(2024, 1, 1), "ps_a"),
            _evt("known-2", date(2024, 3, 15), "ps_a"),
            _evt("unk-1", date(2024, 1, 1), "ps_unknown"),
            _evt("unk-2", date(2024, 8, 1), "ps_unknown"),
        ]
    )
    result = detect_missing_records(graph, [])
    assert all(g.get("patient_scope_id") != "ps_unknown" for g in result["gaps"])
    assert result["summary"]["unassigned_events_excluded"] == 2
