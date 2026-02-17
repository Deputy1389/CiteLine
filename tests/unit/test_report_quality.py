from __future__ import annotations

from datetime import date

from apps.worker.steps.events.report_quality import (
    date_sanity,
    injury_canonicalization,
    is_reportable_fact,
    procedure_canonicalization,
    sanitize_for_report,
    surgery_classifier_guard,
)
from packages.shared.models import Event, EventDate, EventType, Fact, FactKind, DateKind, DateSource


def _event(event_type: EventType, fact_text: str) -> Event:
    return Event(
        event_id="e1",
        provider_id="p1",
        event_type=event_type,
        date=EventDate(kind=DateKind.SINGLE, value=date(2013, 5, 7), source=DateSource.TIER1),
        facts=[Fact(text=fact_text, kind=FactKind.PROCEDURE_NOTE, verbatim=True)],
        confidence=90,
        flags=[],
        citation_ids=[],
        source_page_numbers=[1],
    )


def test_sanitize_for_report_removes_artifacts():
    raw = "Records of Harry Potter PDF_Page 44 Review of Systems Chapman s 38 201two."
    cleaned = sanitize_for_report(raw)
    assert "harry potter" not in cleaned.lower()
    assert "pdf_page" not in cleaned.lower()
    assert "review of systems" not in cleaned.lower()
    assert "chapman" not in cleaned.lower()
    assert "s 38" not in cleaned.lower()
    assert "201two" not in cleaned.lower()


def test_date_sanity():
    assert date_sanity(date(2013, 5, 7)) is True
    assert date_sanity(date(1969, 12, 31)) is False
    assert date_sanity(None) is False


def test_surgery_classifier_guard():
    good = _event(EventType.PROCEDURE, "ORIF and rotator cuff repair with bullet removal")
    bad = _event(EventType.PROCEDURE, "Follow-up visit, pain better")
    historical = _event(EventType.PROCEDURE, "Status post ORIF right shoulder, follow-up clinic visit")
    assert surgery_classifier_guard(good) is True
    assert surgery_classifier_guard(bad) is False
    assert surgery_classifier_guard(historical) is False


def test_procedure_canonicalization():
    text = "Patient underwent ORIF, rotator cuff repair, and bullet removal."
    got = procedure_canonicalization(text)
    assert "orif" in got
    assert "rotator cuff repair" in got
    assert "bullet removal" in got


def test_injury_canonicalization():
    text = "Gunshot wound to shoulder with fracture and wound infection."
    got = injury_canonicalization(text)
    assert "gunshot wound" in got
    assert "shoulder fracture" in got
    assert "wound infection" in got


def test_is_reportable_fact_filters_raw_fragments():
    assert is_reportable_fact("Notes -Encounter Notes (continued) CTA or RUE revealed no vascular injury") is False
    assert is_reportable_fact("Please see their full H&P;/clinic notes for details.") is False
    assert is_reportable_fact("Underwent hardware removal and rotator cuff repair in operating room.") is True
