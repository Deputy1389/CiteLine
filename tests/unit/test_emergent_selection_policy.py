from __future__ import annotations

from datetime import date, timedelta

from apps.worker.project.chronology import build_chronology_projection
from packages.shared.models import DateKind, DateSource, Event, EventDate, EventType, Fact, FactKind


def _event(i: int, txt: str, et: EventType, page: int) -> Event:
    d = date(2025, 1, 1) + timedelta(days=i)
    return Event(
        event_id=f"e-{page}-{i}",
        provider_id="prov",
        event_type=et,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1),
        confidence=85,
        facts=[Fact(text=txt, kind=FactKind.OTHER, verbatim=True)],
        source_page_numbers=[page],
    )


def _run(events: list[Event], pages: int, page_text: str = "clinical note"):
    labels = {i + 1: "Patient A" for i in range(max(pages, len(events) + 5))}
    selection_meta: dict = {}
    projection = build_chronology_projection(
        events=events,
        providers=[],
        page_map=None,
        page_patient_labels=labels,
        page_text_by_number={i + 1: page_text for i in range(max(pages, len(events) + 5))},
        select_timeline=True,
        selection_meta=selection_meta,
    )
    return projection, selection_meta


def test_single_visit_ed_packet_stops_by_saturation():
    events = [
        _event(0, 'Chief complaint: "Neck and back pain after MVC." BP 138/88 pain 8/10 Toradol 30mg IM.', EventType.ER_VISIT, 1),
        _event(1, 'Discharge plan: follow up with PCP and PT.', EventType.HOSPITAL_DISCHARGE, 2),
    ]
    projection, meta = _run(events, pages=13, page_text="ed hpi triage")
    assert 1 <= len(projection.entries) <= 4
    assert meta.get("stopping_reason") in {"saturation", "marginal_utility_non_positive", "no_candidates"}
    assert "target_rows" not in meta


def test_outpatient_packet_keeps_milestones_without_visit_spam():
    events = [
        _event(0, 'Chief complaint: "Neck pain after MVC." BP 140/90 pain 8/10.', EventType.ER_VISIT, 1),
        _event(20, "MRI cervical spine IMPRESSION: C5-6 disc protrusion; mild foraminal narrowing.", EventType.IMAGING_STUDY, 6),
        _event(25, "Orthopedic assessment: cervical radiculopathy. Plan: continue PT; consider ESI.", EventType.OFFICE_VISIT, 8),
        _event(35, "Procedure: epidural steroid injection with Depo-Medrol and lidocaine under fluoroscopy.", EventType.PROCEDURE, 10),
    ]
    for i in range(40):
        events.append(_event(40 + i, f"PT follow-up visit pain {5 + (i % 3)}/10 ROM {30 + i%5} deg strength 4/5.", EventType.PT_VISIT, 20 + i))
    projection, meta = _run(events, pages=60, page_text="pt eval mri ortho")
    assert len(projection.entries) < len(events)
    blob = "\n".join(" ".join(e.facts) + " " + e.event_type_display for e in projection.entries).lower()
    assert "mri" in blob
    assert "orthopedic" in blob or "assessment" in blob
    assert "epidural" in blob or "procedure" in blob
    assert meta.get("stopping_reason") in {"saturation", "marginal_utility_non_positive", "safety_fuse", "no_candidates"}


def test_pt_heavy_large_packet_emits_course_not_micro_visit_dump():
    events: list[Event] = []
    for i in range(220):
        events.append(
            _event(
                i,
                f"PT session pain {4 + (i % 4)}/10 cervical ROM flexion {25 + (i % 15)} deg strength {3 + (i % 2)}/5 plan continue.",
                EventType.PT_VISIT,
                i + 1,
            )
        )
    projection, meta = _run(events, pages=500, page_text="physical therapy progress")
    assert len(projection.entries) <= 120
    assert len(projection.entries) < len(events)
    assert meta.get("stopping_reason") in {"saturation", "marginal_utility_non_positive", "safety_fuse", "no_candidates"}


def test_inpatient_large_packet_prioritizes_milestones_and_filters_meta():
    events: list[Event] = []
    events.append(_event(0, "Hospital admission for acute pain management.", EventType.HOSPITAL_ADMISSION, 1))
    events.append(_event(2, "Procedure: lumbar decompression surgery completed.", EventType.PROCEDURE, 3))
    events.append(_event(5, "MRI lumbar spine IMPRESSION: L4-5 disc protrusion.", EventType.IMAGING_STUDY, 4))
    events.append(_event(7, "Hospital discharge to home with follow-up instructions.", EventType.HOSPITAL_DISCHARGE, 5))
    for i in range(300):
        events.append(_event(10 + i, f"Lab panel: hemoglobin {12 + (i % 2)} g/dL platelet {210 + i%20}.", EventType.LAB_RESULT, 10 + i))
    projection, _meta = _run(events, pages=900, page_text="inpatient discharge summary")
    assert len(projection.entries) < len(events)
    facts_blob = "\n".join(" ".join(e.facts) for e in projection.entries).lower()
    for banned in ("identified from source", "encounter recorded", "markers"):
        assert banned not in facts_blob

