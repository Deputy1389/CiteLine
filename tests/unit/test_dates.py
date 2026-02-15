"""
Unit tests for date extraction (Step 6).
"""
import pytest
from datetime import date
from packages.shared.models import Page, DateSource
from apps.worker.steps.step06_dates import extract_dates


def _make_page(text: str) -> Page:
    return Page(
        page_id="test-page",
        source_document_id="test-doc",
        page_number=1,
        text=text,
        text_source="embedded_pdf_text",
    )


class TestDateExtraction:
    def test_tier1_date_of_service(self):
        page = _make_page("Patient: John\nDate of Service: 03/15/2024\nCC: Back pain")
        dates = extract_dates(page)
        assert len(dates) >= 1
        event_date, label = dates[0]
        assert event_date.source == DateSource.TIER1
        assert event_date.sort_date() == date(2024, 3, 15)

    def test_tier1_encounter_date(self):
        page = _make_page("Encounter Date: 01/10/2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].source == DateSource.TIER1

    def test_tier1_exam_date(self):
        page = _make_page("Exam Date: 03/18/2024\nMRI Lumbar Spine")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].source == DateSource.TIER1
        assert dates[0][0].sort_date() == date(2024, 3, 18)

    def test_tier2_header_date(self):
        page = _make_page("March 15, 2024\n\nSome clinical content here that goes on and on and on to make the page long enough")
        dates = extract_dates(page)
        assert len(dates) >= 1
        # Should be tier2 (header date)

    def test_reject_faxed_on(self):
        page = _make_page("Faxed on: 03/20/2024\nDate of Service: 03/15/2024")
        dates = extract_dates(page)
        # Should not include the fax date, should include DOS
        dos_dates = [d for d, _ in dates if d.sort_date() == date(2024, 3, 15)]
        fax_dates = [d for d, _ in dates if d.sort_date() == date(2024, 3, 20)]
        assert len(dos_dates) >= 1
        assert len(fax_dates) == 0

    def test_reject_printed_on(self):
        page = _make_page("Printed on: 04/01/2024\nVisit Date: 03/22/2024")
        dates = extract_dates(page)
        visit_dates = [d for d, _ in dates if d.sort_date() == date(2024, 3, 22)]
        print_dates = [d for d, _ in dates if d.sort_date() == date(2024, 4, 1)]
        assert len(visit_dates) >= 1
        assert len(print_dates) == 0

    def test_iso_date_format(self):
        page = _make_page("Date of Service: 2024-03-15")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 3, 15)

    def test_month_word_format(self):
        page = _make_page("Date of Service: March 15, 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 3, 15)

    def test_abbreviated_month(self):
        page = _make_page("Date of Service: Mar 15, 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 3, 15)

    def test_no_dates(self):
        page = _make_page("No dates in this text at all")
        dates = extract_dates(page)
        assert len(dates) == 0
