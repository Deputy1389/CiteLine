from __future__ import annotations

from datetime import date

from apps.worker.steps.events.event_weighting import annotate_event_weights, classify_event, severity_score
from packages.shared.models import DateKind, DateSource, Event, EventDate, EventType, Fact, FactKind


def _event(event_type: EventType, text: str) -> Event:
    return Event(
        event_id=f"e-{event_type.value}",
        provider_id="p1",
        event_type=event_type,
        date=EventDate(kind=DateKind.SINGLE, value=date(2024, 1, 1), source=DateSource.TIER1),
        facts=[Fact(text=text, kind=FactKind.OTHER, verbatim=True)],
        confidence=80,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[1],
    )


def test_classify_event_types():
    assert classify_event(_event(EventType.HOSPITAL_ADMISSION, "admitted")) == "admission_discharge"
    assert classify_event(_event(EventType.PROCEDURE, "orif")) == "procedure"
    assert classify_event(_event(EventType.IMAGING_STUDY, "ct")) == "imaging"


def test_severity_prefers_admission_over_vitals():
    admission = _event(EventType.HOSPITAL_ADMISSION, "hospital admission due to infection")
    vitals = _event(EventType.OFFICE_VISIT, "body height body weight blood pressure heart rate")
    assert severity_score(admission) > severity_score(vitals)


def test_annotate_event_weights_sets_extensions():
    events = [
        _event(EventType.PROCEDURE, "hardware removal and debridement"),
        _event(EventType.OFFICE_VISIT, "body weight blood pressure respiratory rate"),
    ]
    summary = annotate_event_weights(events)
    assert summary["event_count"] == 2
    assert "procedure" in summary["by_class"]
    assert isinstance(events[0].extensions.get("severity_score"), int)
    assert isinstance(events[0].extensions.get("is_care_event"), bool)
