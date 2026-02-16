"""
Unit tests for event extraction with P0/P1 changes.
Tests that events are emitted with MISSING_DATE flags instead of being skipped.
"""
import pytest
from datetime import date
from packages.shared.models import (
    DateKind,
    DateSource,
    EventDate,
    EventType,
    Page,
    PageType,
    SkippedEvent,
)
from apps.worker.steps.events.clinical import extract_clinical_events
from apps.worker.steps.events.imaging import extract_imaging_events
from apps.worker.steps.events.billing import extract_billing_events


def _make_page(text: str, page_number: int = 1, page_type=None, doc_id="test-doc"):
    return Page(
        page_id=f"test-page-{page_number}",
        source_document_id=doc_id,
        page_number=page_number,
        text=text,
        text_source="embedded_pdf_text",
        page_type=page_type,
    )


class TestClinicalEventsMissingDate:
    """P0: Clinical events should be emitted even without dates."""

    def test_event_emitted_with_missing_date_flag(self):
        """A clinical page with extractable facts but no date should produce a flagged event."""
        page = _make_page(
            "Chief Complaint:\nLow back pain\n\n"
            "Assessment:\nLumbar strain\n\n"
            "Plan:\nPhysical therapy 3x/week",
            page_type=PageType.CLINICAL_NOTE,
        )
        dates = {}  # No dates available
        events, citations, warnings, skipped = extract_clinical_events(
            [page], dates, [], {}
        )
        # Should produce an event with MISSING_DATE flag, not skip
        assert len(events) >= 1
        flagged = [e for e in events if "MISSING_DATE" in e.flags]
        assert len(flagged) >= 1
        assert flagged[0].date is None

    def test_event_with_date_has_no_flag(self):
        """A clinical page with a valid date should not have MISSING_DATE flag."""
        page = _make_page(
            "Chief Complaint:\nLow back pain\n\n"
            "Assessment:\nLumbar strain",
            page_type=PageType.CLINICAL_NOTE,
        )
        event_date = EventDate(
            kind=DateKind.SINGLE,
            value=date(2024, 3, 15),
            source=DateSource.TIER1,
        )
        dates = {1: [event_date]}
        events, citations, warnings, skipped = extract_clinical_events(
            [page], dates, [], {}
        )
        assert len(events) >= 1
        assert "MISSING_DATE" not in events[0].flags
        assert events[0].date is not None


class TestClinicalSkippedEvents:
    """P1: Skipped events should produce SkippedEvent entries."""

    def test_no_facts_produces_skipped(self):
        """A clinical page with no extractable facts should produce a SkippedEvent."""
        page = _make_page(
            "Some random text without any clinical sections or headers",
            page_type=PageType.CLINICAL_NOTE,
        )
        dates = {1: [EventDate(kind=DateKind.SINGLE, value=date(2024, 1, 1), source=DateSource.TIER1)]}
        events, citations, warnings, skipped = extract_clinical_events(
            [page], dates, [], {}
        )
        assert len(skipped) >= 1
        assert skipped[0].reason_code == "NO_FACTS"


class TestImagingEventsMissingDate:
    """P0: Imaging events should be emitted even without dates."""

    def test_imaging_event_with_no_date(self):
        page = _make_page(
            "MRI Lumbar Spine\n\n"
            "Impression:\nDisc herniation at L4-L5\n"
            "Degenerative changes",
            page_type=PageType.IMAGING_REPORT,
        )
        dates = {}
        events, citations, warnings, skipped = extract_imaging_events(
            [page], dates, [], {}
        )
        assert len(events) >= 1
        assert "MISSING_DATE" in events[0].flags
        assert events[0].date is None

    def test_imaging_no_impression_skipped(self):
        page = _make_page(
            "MRI of the lumbar spine was performed",
            page_type=PageType.IMAGING_REPORT,
        )
        dates = {}
        events, citations, warnings, skipped = extract_imaging_events(
            [page], dates, [], {}
        )
        assert len(events) == 0
        assert len(skipped) >= 1
        assert skipped[0].reason_code == "NO_TRIGGER_MATCH"


class TestBillingEventsMissingDate:
    """P0: Billing events should be emitted even without dates."""

    def test_billing_event_with_no_date(self):
        page = _make_page(
            "Medical Billing Statement\n"
            "Total Amount Due: $1,500.00\n"
            "Patient: John Doe",
            page_type=PageType.BILLING,
        )
        dates = {}
        events, citations, warnings, skipped = extract_billing_events(
            [page], dates, [], {}
        )
        assert len(events) >= 1
        assert "MISSING_DATE" in events[0].flags
        assert events[0].date is None
        # BillingDetails should be None when no date available
        assert events[0].billing is None

    def test_billing_no_amount_skipped(self):
        page = _make_page(
            "Account Statement\nNo charges",
            page_type=PageType.BILLING,
        )
        dates = {}
        events, citations, warnings, skipped = extract_billing_events(
            [page], dates, [], {}
        )
        assert len(events) == 0
        assert len(skipped) >= 1
        assert skipped[0].reason_code == "NO_TRIGGER_MATCH"


class TestSkippedEventModel:
    """P1: SkippedEvent model should validate correctly."""

    def test_skipped_event_creation(self):
        se = SkippedEvent(
            page_numbers=[1, 2],
            reason_code="MISSING_DATE",
            snippet="Day 1, 0900 Bedrest BRP",
        )
        assert se.page_numbers == [1, 2]
        assert se.reason_code == "MISSING_DATE"
        assert len(se.snippet) > 0
