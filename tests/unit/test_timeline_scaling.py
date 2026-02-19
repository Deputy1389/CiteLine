from __future__ import annotations

from datetime import date, timedelta

from apps.worker.project.chronology import build_chronology_projection
from packages.shared.models import DateKind, DateSource, Event, EventDate, EventType, Fact, FactKind


def _evt(i: int, text: str, event_type: EventType = EventType.OFFICE_VISIT) -> Event:
    d = date(2025, 1, 1) + timedelta(days=i)
    return Event(
        event_id=f"evt-{i}",
        provider_id="prov1",
        event_type=event_type,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1),
        confidence=80,
        facts=[Fact(text=text, kind=FactKind.OTHER, verbatim=True)],
        source_page_numbers=[i + 1],
    )


def test_emergent_selection_stops_on_saturation_not_fixed_floor():
    events = [
        _evt(i, "Physical therapy follow-up. Pain score 6/10. Cervical ROM flexion 30 deg. Strength 4/5.")
        for i in range(80)
    ]
    labels = {i + 1: "Patient A" for i in range(80)}
    selection_meta: dict = {}
    projection = build_chronology_projection(
        events=events,
        providers=[],
        page_map=None,
        page_patient_labels=labels,
        page_text_by_number={i + 1: "PT follow-up note pain 6/10 ROM 30 deg strength 4/5" for i in range(80)},
        select_timeline=True,
        selection_meta=selection_meta,
    )
    assert 0 < len(projection.entries) < len(events)
    assert selection_meta.get("stopping_reason") in {"saturation", "marginal_utility_non_positive", "safety_fuse", "no_candidates"}
    assert isinstance(selection_meta.get("delta_u_trace"), list)


def test_milestone_bucket_constraints_when_present():
    events = [
        _evt(0, 'Chief complaint: "Neck pain after MVC." BP 138/88. Toradol 30mg IM.', EventType.ER_VISIT),
        _evt(5, 'MRI cervical spine IMPRESSION: C5-6 disc protrusion with mild foraminal narrowing.', EventType.IMAGING_STUDY),
        _evt(10, 'Orthopedic assessment: cervical radiculopathy. Plan: continue PT and consider ESI.', EventType.OFFICE_VISIT),
        _evt(12, 'Procedure: epidural steroid injection at C6-7 with Depo-Medrol and lidocaine under fluoroscopy.', EventType.PROCEDURE),
    ]
    labels = {i + 1: "Patient A" for i in range(20)}
    projection = build_chronology_projection(
        events=events,
        providers=[],
        page_map=None,
        page_patient_labels=labels,
        page_text_by_number={i + 1: "clinical note" for i in range(20)},
        select_timeline=True,
    )
    blob = "\n".join(" ".join(e.facts) + " " + e.event_type_display for e in projection.entries).lower()
    assert "emergency" in blob or "chief complaint" in blob
    assert "mri" in blob or "impression" in blob
    assert "orthopedic" in blob or "assessment" in blob
    assert "epidural" in blob or "procedure" in blob
