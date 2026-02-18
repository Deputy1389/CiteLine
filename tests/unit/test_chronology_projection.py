from __future__ import annotations

from datetime import date

from apps.worker.project.chronology import build_chronology_projection, infer_page_patient_labels
from packages.shared.models import (
    DateKind,
    DateSource,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Provider,
    ProviderType,
)


def _event(
    event_id: str,
    event_type: EventType,
    fact_texts: list[str],
    with_date: bool = True,
    provider_id: str | None = "p1",
) -> Event:
    event_date = None
    if with_date:
        event_date = EventDate(kind=DateKind.SINGLE, value=date(2013, 5, 21), source=DateSource.TIER1)
    return Event(
        event_id=event_id,
        provider_id=provider_id,
        event_type=event_type,
        date=event_date,
        facts=[Fact(text=t, kind=FactKind.OTHER, verbatim=True) for t in fact_texts],
        confidence=80,
        flags=[],
        citation_ids=[],
        source_page_numbers=[1],
    )


def test_projection_drops_undated_low_value_events():
    events = [
        _event("dated", EventType.IMAGING_STUDY, ["Impression: comminuted fracture and retained fragments."], with_date=True),
        _event("undated", EventType.OFFICE_VISIT, ["Follow up in clinic."], with_date=False),
    ]
    providers = [
        Provider(
            provider_id="p1",
            detected_name_raw="Interim LSU Public Hospital",
            normalized_name="Interim LSU Public Hospital",
            provider_type=ProviderType.HOSPITAL,
            confidence=90,
        )
    ]
    projection = build_chronology_projection(events, providers)
    ids = [entry.event_id for entry in projection.entries]
    assert "dated" in ids
    assert "undated" not in ids


def test_projection_provider_guard_for_radiology_non_imaging():
    events = [
        _event("office", EventType.OFFICE_VISIT, ["Assessment: shoulder pain and wound infection."], with_date=True, provider_id="rad")
    ]
    providers = [
        Provider(
            provider_id="rad",
            detected_name_raw="Erick Brick MD Radiology",
            normalized_name="Erick Brick MD Radiology",
            provider_type=ProviderType.IMAGING,
            confidence=95,
        )
    ]
    projection = build_chronology_projection(events, providers)
    assert projection.entries
    assert projection.entries[0].provider_display == "Unknown"


def test_projection_drops_vitals_only_inpatient_note():
    event = _event(
        "vitals-only",
        EventType.INPATIENT_DAILY_NOTE,
        [
            "Body Height: 150 cm; Body Weight: 70 kg; Diastolic Blood Pressure: 80 mm[Hg]; Systolic Blood Pressure: 120 mm[Hg]",
            "Heart rate: 70 /min; Respiratory rate: 14 /min; Pain severity score: 2",
        ],
        with_date=True,
        provider_id=None,
    )
    projection = build_chronology_projection([event], providers=[])
    assert projection.entries == []


def test_infer_page_patient_labels_for_synthea_pattern():
    labels = infer_page_patient_labels(
        {
            1: "Derek111 Lehner980\nSome encounter text",
            2: "No patient header here",
            3: "Patient Name: Jane Doe\nVisit details",
            4: "No patient header here either",
        }
    )
    assert labels[1] == "Derek111 Lehner980"
    assert labels[3] == "Jane Doe"
    assert labels[4] == "Jane Doe"


def test_projection_demotes_routine_lab_result():
    event = _event(
        "lab-routine",
        EventType.LAB_RESULT,
        ["Labs found: Hemoglobin, Hematocrit, Platelet."],
        with_date=True,
        provider_id="p1",
    )
    providers = [
        Provider(
            provider_id="p1",
            detected_name_raw="Interim LSU Public Hospital",
            normalized_name="Interim LSU Public Hospital",
            provider_type=ProviderType.HOSPITAL,
            confidence=90,
        )
    ]
    projection = build_chronology_projection([event], providers)
    assert projection.entries == []


def test_projection_strips_conflicting_embedded_timestamp():
    event = Event(
        event_id="ts-mismatch",
        provider_id="p1",
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=date(2017, 1, 8), source=DateSource.TIER1),
        facts=[
            Fact(
                text="Follow-up documented (2017-02-05T11:31:13Z) with medication review and disposition.",
                kind=FactKind.OTHER,
                verbatim=True,
            )
        ],
        confidence=85,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[1],
        extensions={"severity_score": 60},
    )
    projection = build_chronology_projection([event], providers=[])
    assert projection.entries
    assert "2017-02-05T11:31:13Z" not in " ".join(projection.entries[0].facts)
