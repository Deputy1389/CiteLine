from __future__ import annotations

from datetime import date

from apps.worker.project.chronology import build_chronology_projection
from packages.shared.models import DateKind, DateSource, Event, EventDate, EventType, Fact, FactKind


def _evt(i: int) -> Event:
    d = date(2025, 1, 1).replace(day=min(28, (i % 28) + 1))
    return Event(
        event_id=f"evt-{i}",
        provider_id="prov1",
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1),
        confidence=80,
        facts=[Fact(text="Follow-up visit. Pain 5/10. Cervical ROM flexion 35 deg. Strength 4/5.", kind=FactKind.OTHER, verbatim=True)],
        source_page_numbers=[i + 1],
    )


def test_projection_uses_emergent_selection_not_fixed_floor():
    events = [_evt(i) for i in range(40)]
    labels = {i + 1: "Patient A" for i in range(40)}
    selection_meta: dict = {}
    projection = build_chronology_projection(
        events=events,
        providers=[],
        page_map=None,
        page_patient_labels=labels,
        page_text_by_number={i + 1: "Follow-up note Pain 5/10 ROM 35 deg strength 4/5." for i in range(40)},
        select_timeline=True,
        selection_meta=selection_meta,
    )
    assert len(projection.entries) <= len(events)
    assert selection_meta.get("stopping_reason") in {"saturation", "marginal_utility_non_positive", "safety_fuse"}
    assert selection_meta.get("events_final_count") is None or isinstance(selection_meta.get("events_final_count"), int)

