from __future__ import annotations

from datetime import date

from apps.worker.project.chronology import (
    _apply_timeline_selection,
    build_chronology_projection,
    compute_provider_resolution_quality,
    infer_page_patient_labels,
    _propagate_pt_provider_labels,
)
from apps.worker.project.models import ChronologyProjectionEntry
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
    RunConfig,
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


def test_safe_pt_provider_propagation_fills_unknown_therapy_rows_when_single_consistent_provider():
    rows = [
        ChronologyProjectionEntry(
            event_id="d1", date_display="2025-11-16", provider_display="Elite Physical Therapy",
            event_type_display="Discharge", patient_label="See Patient Header",
            facts=["Elite Physical Therapy DISCHARGE SUMMARY"], citation_display="p. 348", confidence=80
        ),
        ChronologyProjectionEntry(
            event_id="d1b", date_display="2025-11-16", provider_display="Elite Physical Therapy",
            event_type_display="Therapy Visit", patient_label="See Patient Header",
            facts=["Elite Physical Therapy DISCHARGE SUMMARY"], citation_display="p. 348", confidence=80
        ),
        ChronologyProjectionEntry(
            event_id="t1", date_display="Date not documented", provider_display="Unknown",
            event_type_display="Therapy Visit", patient_label="See Patient Header",
            facts=["Aggregated PT sessions (117 encounters) (ROM, Strength)"], citation_display="p. 230", confidence=80
        ),
        ChronologyProjectionEntry(
            event_id="t2", date_display="Date not documented", provider_display="Provider not stated",
            event_type_display="Therapy Visit", patient_label="See Patient Header",
            facts=["Aggregated PT sessions (6 encounters) (ROM, Strength)"], citation_display="p. 52", confidence=80
        ),
    ]
    out = _propagate_pt_provider_labels(rows)
    therapy_rows = [r for r in out if r.event_type_display == "Therapy Visit"]
    assert all(r.provider_display == "Elite Physical Therapy" for r in therapy_rows)


def test_safe_pt_provider_propagation_keeps_unknown_when_multiple_pt_providers():
    rows = [
        ChronologyProjectionEntry(
            event_id="d1", date_display="2025-11-16", provider_display="Elite Physical Therapy",
            event_type_display="Discharge", patient_label="See Patient Header",
            facts=["Elite Physical Therapy DISCHARGE SUMMARY"], citation_display="p. 348", confidence=80
        ),
        ChronologyProjectionEntry(
            event_id="d2", date_display="2025-10-01", provider_display="Pinnacle Rehab",
            event_type_display="Discharge", patient_label="See Patient Header",
            facts=["Pinnacle Rehab discharge"], citation_display="p. 200", confidence=80
        ),
        ChronologyProjectionEntry(
            event_id="t1", date_display="Date not documented", provider_display="Unknown",
            event_type_display="Therapy Visit", patient_label="See Patient Header",
            facts=["Aggregated PT sessions (117 encounters)"], citation_display="p. 230", confidence=80
        ),
    ]
    out = _propagate_pt_provider_labels(rows)
    t1 = next(r for r in out if r.event_id == "t1")
    assert t1.provider_display == "Unknown"


def test_safe_pt_provider_propagation_uses_pt_cited_page_evidence_when_row_labels_unknown():
    rows = [
        ChronologyProjectionEntry(
            event_id="pt_ref1", date_display="2025-11-01", provider_display="Unknown",
            event_type_display="Therapy Visit", patient_label="See Patient Header",
            facts=["Physical therapy re-evaluation with ROM and strength testing"], citation_display="p. 10", confidence=80
        ),
        ChronologyProjectionEntry(
            event_id="pt_ref2", date_display="2025-11-03", provider_display="Provider not clearly identified",
            event_type_display="Discharge", patient_label="See Patient Header",
            facts=["Physical therapy discharge summary"], citation_display="p. 11", confidence=80
        ),
        ChronologyProjectionEntry(
            event_id="pt_target", date_display="Date not documented", provider_display="Unknown",
            event_type_display="Therapy Visit", patient_label="See Patient Header",
            facts=["Aggregated PT sessions (24 encounters)"], citation_display="p. 12", confidence=80
        ),
    ]
    providers = [
        Provider(
            provider_id="pt1",
            detected_name_raw="Elite Physical Therapy",
            normalized_name="Elite Physical Therapy",
            provider_type=ProviderType.PT,
            confidence=92,
        )
    ]
    out = _propagate_pt_provider_labels(
        rows,
        providers=providers,
        page_provider_map={10: "pt1", 11: "pt1"},
    )
    target = next(r for r in out if r.event_id == "pt_target")
    assert target.provider_display == "Elite Physical Therapy"


def test_projection_infers_synthetic_procedure_anchor_provider_from_page_provider_map():
    providers = [
        Provider(
            provider_id="pain1",
            detected_name_raw="Advanced Pain Specialists",
            normalized_name="Advanced Pain Specialists",
            provider_type=ProviderType.SPECIALIST,
            confidence=95,
        )
    ]
    projection = build_chronology_projection(
        events=[],
        providers=providers,
        page_provider_map={25: "pain1"},
        page_text_by_number={
            25: "Procedure note 2025-01-14 fluoroscopy guided transforaminal epidural injection with depo-medrol and lidocaine. Complications: none."
        },
    )
    proc_rows = [r for r in projection.entries if r.event_id.startswith("proc_anchor_")]
    assert proc_rows
    assert proc_rows[0].provider_display == "Advanced Pain Specialists"


def test_compute_provider_resolution_quality_groups_unresolved_by_family():
    rows = [
        ChronologyProjectionEntry(
            event_id="img1", date_display="2025-01-01", provider_display="Radiology Group",
            event_type_display="Imaging Study", patient_label="P",
            facts=["MRI impression documented"], citation_display="p. 1", confidence=90
        ),
        ChronologyProjectionEntry(
            event_id="pt1", date_display="2025-01-02", provider_display="Provider not clearly identified",
            event_type_display="Therapy Visit", patient_label="P",
            facts=["Physical therapy evaluation with ROM and strength"], citation_display="p. 2", confidence=80
        ),
        ChronologyProjectionEntry(
            event_id="proc1", date_display="2025-01-03", provider_display="Unknown",
            event_type_display="Procedure/Surgery", patient_label="P",
            facts=["Fluoroscopy-guided injection"], citation_display="p. 3", confidence=85
        ),
        ChronologyProjectionEntry(
            event_id="admin1", date_display="2025-01-04", provider_display="Unknown",
            event_type_display="Clinical Note", patient_label="P",
            facts=["Insurance intake demographics"], citation_display="", confidence=20
        ),
    ]
    payload = compute_provider_resolution_quality(rows)
    assert payload["rows_total"] == 3
    assert payload["rows_resolved"] == 1
    assert payload["rows_unresolved"] == 2
    assert payload["resolved_ratio"] == 0.3333
    assert payload["unresolved_by_family"]["therapy"] == 1
    assert payload["unresolved_by_family"]["surgery_procedure"] == 1
    assert payload["by_family"]["imaging_impression"]["rows_resolved"] == 1


def test_projection_preserves_verbatim_flags_from_event_facts():
    event = Event(
        event_id="verbatim-ed",
        provider_id="p1",
        event_type=EventType.ER_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=date(2020, 1, 2), source=DateSource.TIER1),
        facts=[
            Fact(text="Chief complaint: rear-end collision with neck pain 8/10.", kind=FactKind.OTHER, verbatim=True),
            Fact(text="Assessment: cervical strain.", kind=FactKind.OTHER, verbatim=False),
        ],
        confidence=90,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[1],
    )
    projection = build_chronology_projection([event], providers=[])
    assert projection.entries
    entry = projection.entries[0]
    assert len(entry.verbatim_flags) == len(entry.facts)
    assert any(entry.verbatim_flags)


def test_projection_falls_back_to_emergency_department_label_for_unknown_ed_provider():
    event = Event(
        event_id="ed-unknown-provider",
        provider_id=None,
        event_type=EventType.ER_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=date(2025, 1, 2), source=DateSource.TIER1),
        facts=[Fact(text="Chief complaint: rear-end collision with neck pain 8/10.", kind=FactKind.OTHER, verbatim=True)],
        confidence=90,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[1],
    )
    projection = build_chronology_projection([event], providers=[])
    assert projection.entries
    assert projection.entries[0].event_type_display == "Emergency Visit"
    assert projection.entries[0].provider_display == "Emergency Department"


def test_projection_falls_back_to_emergency_department_when_ed_marker_on_source_page():
    event = Event(
        event_id="ed-page-marker",
        provider_id=None,
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=date(2025, 1, 2), source=DateSource.TIER1),
        facts=[Fact(text="General Hospital & Trauma Center 8/10", kind=FactKind.OTHER, verbatim=False)],
        confidence=75,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[5],
    )
    projection = build_chronology_projection(
        [event],
        providers=[],
        page_text_by_number={5: "Emergency Department ED HPI chief complaint neck pain"},
    )
    assert projection.entries
    assert projection.entries[0].provider_display == "Emergency Department"


def test_selection_forces_ed_bucket_when_source_markers_exist_and_provider_unresolved():
    rows = [
        ChronologyProjectionEntry(
            event_id="ed-low",
            date_display="2025-01-01",
            provider_display="Unknown",
            event_type_display="Clinical Note",
            patient_label="See Patient Header",
            facts=["Patient seen."],
            citation_display="packet.pdf p. 1",
            confidence=10,
        ),
        ChronologyProjectionEntry(
            event_id="fu-1",
            date_display="2025-01-05",
            provider_display="Clinic A",
            event_type_display="Follow-Up Visit",
            patient_label="See Patient Header",
            facts=["Assessment: cervical strain. Plan: continue PT."],
            citation_display="packet.pdf p. 3",
            confidence=80,
        ),
    ]
    selection_meta: dict = {}
    out = _apply_timeline_selection(
        rows,
        total_pages=3,
        selection_meta=selection_meta,
        providers=[],
        page_provider_map={},
        page_text_by_number={1: "ED NOTES. Chief Complaint neck pain 8/10. HPI after collision."},
        config=RunConfig(),
    )
    ids = {r.event_id for r in out}
    assert "ed-low" in ids
    forced = selection_meta.get("forced_required_event_buckets") or {}
    assert forced.get("ed-low") == "ed"
    missing = [m for m in (selection_meta.get("required_bucket_missing_after_selection") or []) if m.get("bucket") == "ed"]
    assert not missing


def test_selection_prevents_last_ed_drop_under_row_cap_with_required_guard():
    rows = [
        ChronologyProjectionEntry(
            event_id="ed-keep",
            date_display="2025-01-01",
            provider_display="Unknown",
            event_type_display="Clinical Note",
            patient_label="See Patient Header",
            facts=["Brief note."],
            citation_display="packet.pdf p. 1",
            confidence=5,
        ),
        ChronologyProjectionEntry(
            event_id="strong-followup",
            date_display="2025-01-02",
            provider_display="Specialist",
            event_type_display="Follow-Up Visit",
            patient_label="See Patient Header",
            facts=["Assessment: radiculopathy. Plan: procedure referral."],
            citation_display="packet.pdf p. 2",
            confidence=95,
        ),
    ]
    selection_meta: dict = {}
    out = _apply_timeline_selection(
        rows,
        total_pages=2,
        selection_meta=selection_meta,
        providers=[],
        page_provider_map={},
        page_text_by_number={1: "Emergency Department triage. HPI rear-end collision."},
        config=RunConfig(chronology_selection_hard_max_rows=1),
    )
    # Required-bucket guard may exceed hard row cap to preserve ED coverage.
    assert any(r.event_id == "ed-keep" for r in out)
    missing = [m for m in (selection_meta.get("required_bucket_missing_after_selection") or []) if m.get("bucket") == "ed"]
    assert not missing


def test_selection_drops_low_fact_density_metadata_rows():
    rows = [
        ChronologyProjectionEntry(
            event_id="weak-meta",
            date_display="2025-01-03",
            provider_display="Unknown",
            event_type_display="Follow-Up Visit",
            patient_label="See Patient Header",
            facts=["Follow-up pain 8/10 today"],
            citation_display="packet.pdf p. 7",
            confidence=40,
        ),
        ChronologyProjectionEntry(
            event_id="strong-row",
            date_display="2025-01-04",
            provider_display="Clinic A",
            event_type_display="Follow-Up Visit",
            patient_label="See Patient Header",
            facts=["Assessment: cervical radiculopathy. Plan: continue therapy and home exercise."],
            citation_display="packet.pdf p. 8",
            confidence=80,
        ),
    ]
    selection_meta: dict = {}
    out = _apply_timeline_selection(
        rows,
        total_pages=8,
        selection_meta=selection_meta,
        providers=[],
        page_provider_map={},
        page_text_by_number={},
        config=RunConfig(),
    )
    ids = {r.event_id for r in out}
    assert "strong-row" in ids
    assert "weak-meta" not in ids
    drops = [d for d in (selection_meta.get("dropped_rows_audit") or []) if d.get("event_id") == "weak-meta"]
    assert any(d.get("reason") == "DROPPED_LOW_FACT_DENSITY" for d in drops)
