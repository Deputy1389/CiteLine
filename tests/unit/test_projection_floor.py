from __future__ import annotations

from datetime import date

from apps.worker.project.chronology import build_chronology_projection
from packages.shared.models import Event, EventDate, EventType, Fact, FactKind, DateKind, DateSource


def _evt(i: int) -> Event:
    d = date(2025, 1, 1).replace(day=min(28, (i % 28) + 1))
    return Event(
        event_id=f"evt-{i}",
        provider_id="prov1",
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1),
        confidence=80,
        facts=[
            Fact(
                text="Follow-up visit with assessment and treatment plan documented.",
                kind=FactKind.OTHER,
                verbatim=True,
            )
        ],
        source_page_numbers=[i + 1],
    )


def test_projection_enforces_coverage_floor_when_candidates_exist():
    events = [_evt(i) for i in range(40)]
    labels = {i + 1: "Patient A" for i in range(40)}
    projection = build_chronology_projection(
        events=events,
        providers=[],
        page_map=None,
        page_patient_labels=labels,
        page_text_by_number={i + 1: "Follow-up note" for i in range(40)},
        select_timeline=True,
    )
    assert len(projection.entries) >= 25

