from apps.worker.steps.events.encounter_classifier import PRIORITY_MAP, detect_encounter_type
from packages.shared.models import EventType


def test_detect_encounter_type_marks_pt_eval_as_office_visit() -> None:
    text = (
        "Elite Physical Therapy\n"
        "Functional Status:\n"
        "Physical Examination:\n"
        "Range of Motion: Cervical ROM reduced.\n"
    )
    assert detect_encounter_type(text) == EventType.OFFICE_VISIT


def test_detect_encounter_type_marks_treatment_plan_discussion_as_office_visit() -> None:
    text = (
        "ASSESSMENT AND TREATMENT PLAN\n"
        "TREATMENT PLAN DISCUSSION:\n"
        "Modified duty. Follow up in 4 weeks with orthopedic clinic."
    )
    assert detect_encounter_type(text) == EventType.OFFICE_VISIT


def test_office_visit_priority_exceeds_inpatient_daily_note() -> None:
    assert PRIORITY_MAP[EventType.OFFICE_VISIT] > PRIORITY_MAP[EventType.INPATIENT_DAILY_NOTE]
