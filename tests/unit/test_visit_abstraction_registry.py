from datetime import date

from apps.worker.steps.step_visit_abstraction_registry import build_competitive_registries
from packages.shared.models import Event, EventDate, Fact, Provider
from packages.shared.models.enums import DateKind, DateSource, DateStatus, EventType, FactKind, ProviderType


def _fact(text: str) -> Fact:
    return Fact(text=text, kind=FactKind.OTHER, verbatim=False, citation_ids=["c1"])


def _event(event_id: str, event_type: EventType, provider_id: str, d: date, *,
           complaint: str = "", facts: list[Fact] | None = None,
           diagnoses: list[Fact] | None = None, treatment_plan: list[Fact] | None = None,
           procedures: list[Fact] | None = None) -> Event:
    return Event(
        event_id=event_id,
        provider_id=provider_id,
        event_type=event_type,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1, status=DateStatus.EXPLICIT),
        chief_complaint=complaint or None,
        facts=facts or [],
        diagnoses=diagnoses or [],
        treatment_plan=treatment_plan or [],
        procedures=procedures or [],
        confidence=80,
        citation_ids=["c1"],
    )


def test_pt_encounter_does_not_require_diagnosis_bucket() -> None:
    providers = [
        Provider(
            provider_id="p_pt",
            detected_name_raw="Elite PT",
            normalized_name="Elite PT",
            provider_type=ProviderType.PT,
            confidence=90,
        )
    ]
    events = [
        _event(
            "e1",
            EventType.PT_VISIT,
            "p_pt",
            date(2025, 1, 10),
            complaint="Shoulder pain persists",
            facts=[_fact("Difficulty lifting right arm above shoulder")],
            treatment_plan=[_fact("Continue physical therapy and home exercise")],
        )
    ]

    out = build_competitive_registries(events=events, providers=providers, citations=[])
    rows = out.get("visit_abstraction_registry") or []
    assert len(rows) == 1
    assert rows[0]["encounter_type"] == "therapy"
    assert rows[0]["bucket_completeness_pass"] is True
    assert "diagnoses" not in set(rows[0]["missing_required_buckets"])


def test_er_encounter_missing_treatment_fails_required_bucket() -> None:
    providers = [
        Provider(
            provider_id="p_er",
            detected_name_raw="County ER",
            normalized_name="County ER",
            provider_type=ProviderType.ER,
            confidence=90,
        )
    ]
    events = [
        _event(
            "e2",
            EventType.ER_VISIT,
            "p_er",
            date(2025, 1, 2),
            complaint="Neck pain after motor vehicle collision",
            facts=[_fact("Exam shows cervical tenderness and reduced ROM")],
            diagnoses=[_fact("Cervical strain")],
            treatment_plan=[],
            procedures=[],
        )
    ]

    out = build_competitive_registries(events=events, providers=providers, citations=[])
    rows = out.get("visit_abstraction_registry") or []
    assert len(rows) == 1
    assert rows[0]["encounter_type"] == "er"
    assert rows[0]["bucket_completeness_pass"] is False
    assert "treatments" in set(rows[0]["missing_required_buckets"])


def test_provider_role_registry_and_diagnosis_registry_are_deterministic() -> None:
    providers = [
        Provider(
            provider_id="p1",
            detected_name_raw="Ortho A",
            normalized_name="Ortho A",
            provider_type=ProviderType.SPECIALIST,
            confidence=90,
        ),
        Provider(
            provider_id="p2",
            detected_name_raw="Radiology B",
            normalized_name="Radiology B",
            provider_type=ProviderType.IMAGING,
            confidence=90,
        ),
    ]
    events = [
        _event(
            "e3",
            EventType.OFFICE_VISIT,
            "p1",
            date(2025, 1, 3),
            complaint="Shoulder pain",
            diagnoses=[_fact("AC joint separation S43.121")],
            treatment_plan=[_fact("Orthopedic follow-up planned")],
        ),
        _event(
            "e4",
            EventType.IMAGING_STUDY,
            "p2",
            date(2025, 1, 4),
            facts=[_fact("MRI shoulder shows labral tear")],
            diagnoses=[_fact("Labral tear")],
        ),
    ]

    out1 = build_competitive_registries(events=events, providers=providers, citations=[])
    out2 = build_competitive_registries(events=events, providers=providers, citations=[])

    assert out1["provider_role_registry"] == out2["provider_role_registry"]
    assert out1["diagnosis_registry"] == out2["diagnosis_registry"]
    assert any(r["provider_role"] == "specialist" for r in out1["provider_role_registry"])
    assert any(r["provider_role"] == "imaging" for r in out1["provider_role_registry"])
    assert any("S43.121" in (r.get("icd_codes") or []) for r in out1["diagnosis_registry"])
