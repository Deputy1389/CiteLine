"""
Unit tests for date extraction (Step 6).
"""
import pytest
from datetime import date
from packages.shared.models import Page, DateSource, EventDate
from apps.worker.steps.step06_dates import (
    extract_dates,
    extract_dates_for_pages,
    _find_anchor_date,
    _resolve_relative_dates,
)


def _make_page(text: str, page_number: int = 1, doc_id: str = "test-doc") -> Page:
    return Page(
        page_id=f"test-page-{page_number}",
        source_document_id=doc_id,
        page_number=page_number,
        text=text,
        text_source="embedded_pdf_text",
    )


# ── Original tests (preserved) ──────────────────────────────────────────


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
        page = _make_page(
            "March 15, 2024\n\nSome clinical content here that goes on "
            "and on and on to make the page long enough"
        )
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


# ── Ordinal date tests ───────────────────────────────────────────────────


class TestOrdinalDates:
    def test_month_ddth_yyyy(self):
        page = _make_page("Date of Service: March 14th, 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 3, 14)

    def test_month_ddst_yyyy(self):
        page = _make_page("Encounter Date: January 1st, 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 1, 1)

    def test_month_ddnd_yyyy(self):
        page = _make_page("Visit Date: Jan 2nd, 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 1, 2)

    def test_month_ddrd_yyyy(self):
        page = _make_page("Exam Date: February 3rd, 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 2, 3)

    def test_ordinal_without_comma(self):
        page = _make_page("Service Date: July 16th 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 7, 16)


# ── DD Month YYYY tests ─────────────────────────────────────────────────


class TestDDMonthYYYY:
    def test_dd_month_yyyy(self):
        page = _make_page("Date of Service: 14 March 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 3, 14)

    def test_dd_month_yyyy_with_comma(self):
        page = _make_page("Encounter Date: 22 December, 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 12, 22)

    def test_dd_abbreviated_month_yyyy(self):
        page = _make_page("Visit Date: 5 Sep 2024")
        dates = extract_dates(page)
        assert len(dates) >= 1
        assert dates[0][0].sort_date() == date(2024, 9, 5)


# ── Anchor date tests ───────────────────────────────────────────────────


class TestAnchorDates:
    def test_admission_date_detected(self):
        pages = [
            _make_page(
                "Patient Chart\nAdmission Date: 01/15/2024\nBedrest\n"
                "More content to fill the page out a bit more and more text",
                page_number=1,
            )
        ]
        anchor = _find_anchor_date(pages)
        assert anchor == date(2024, 1, 15)

    def test_admit_date_detected(self):
        pages = [
            _make_page(
                "PATIENT RECORD\nAdmit Date: 03/01/2024\nAllergies: NKDA",
                page_number=1,
            )
        ]
        anchor = _find_anchor_date(pages)
        assert anchor == date(2024, 3, 1)

    def test_date_admitted_detected(self):
        pages = [
            _make_page(
                "Patient: Millie\nDate Admitted: 06/10/2024\nRoom: 616",
                page_number=1,
            )
        ]
        anchor = _find_anchor_date(pages)
        assert anchor == date(2024, 6, 10)

    def test_date_of_service_as_anchor(self):
        pages = [
            _make_page(
                "Date of Service: 05/20/2024\nChief Complaint: Headache",
                page_number=1,
            )
        ]
        anchor = _find_anchor_date(pages)
        assert anchor == date(2024, 5, 20)

    def test_no_anchor_returns_none(self):
        pages = [_make_page("No labeled dates here at all")]
        anchor = _find_anchor_date(pages)
        assert anchor is None

    def test_anchor_from_second_page(self):
        pages = [
            _make_page("Cover page with no dates", page_number=1),
            _make_page("Admission Date: 02/14/2024\nContent", page_number=2),
        ]
        anchor = _find_anchor_date(pages)
        assert anchor == date(2024, 2, 14)


# ── Relative date tests ─────────────────────────────────────────────────


class TestRelativeDates:
    def test_day_1_resolves_to_anchor(self):
        anchor = date(2024, 1, 15)
        page = _make_page("Day 1, 0900\nBedrest, BRP with assist")
        resolved = _resolve_relative_dates(page, anchor)
        assert len(resolved) >= 1
        assert resolved[0].sort_date() == date(2024, 1, 15)
        assert resolved[0].source == DateSource.ANCHOR

    def test_day_2_resolves_to_anchor_plus_1(self):
        anchor = date(2024, 1, 15)
        page = _make_page("Day 2\nPatient resting comfortably")
        resolved = _resolve_relative_dates(page, anchor)
        assert len(resolved) >= 1
        assert resolved[0].sort_date() == date(2024, 1, 16)

    def test_day_3_resolves_correctly(self):
        anchor = date(2024, 1, 15)
        page = _make_page("Hospital Day 3\nVital signs stable")
        resolved = _resolve_relative_dates(page, anchor)
        assert len(resolved) >= 1
        assert resolved[0].sort_date() == date(2024, 1, 17)

    def test_postop_day_1(self):
        anchor = date(2024, 3, 10)
        page = _make_page("Post-op Day 1\nPatient tolerating PO diet")
        resolved = _resolve_relative_dates(page, anchor)
        assert len(resolved) >= 1
        assert resolved[0].sort_date() == date(2024, 3, 11)

    def test_pod_abbreviation(self):
        anchor = date(2024, 3, 10)
        page = _make_page("POD 2\nDressing changed, wound clean")
        resolved = _resolve_relative_dates(page, anchor)
        assert len(resolved) >= 1
        assert resolved[0].sort_date() == date(2024, 3, 12)

    def test_no_relative_dates(self):
        anchor = date(2024, 1, 15)
        page = _make_page("No relative dates here")
        resolved = _resolve_relative_dates(page, anchor)
        assert len(resolved) == 0

    def test_duplicate_day_references_deduplicated(self):
        anchor = date(2024, 1, 15)
        page = _make_page("Day 1, 0900\nBedrest\nDay 1:\nSee flow sheet")
        resolved = _resolve_relative_dates(page, anchor)
        # Should only produce one date even though "Day 1" appears twice
        assert len(resolved) == 1


# ── Header propagation tests ────────────────────────────────────────────


class TestHeaderPropagation:
    def test_propagation_to_next_page(self):
        pages = [
            _make_page(
                "Date of Service: 03/15/2024\nPatient seen with back pain",
                page_number=1,
            ),
            _make_page("Continued from previous page. No date here.", page_number=2),
        ]
        result = extract_dates_for_pages(pages)
        assert 1 in result
        assert 2 in result
        assert result[2][0].sort_date() == date(2024, 3, 15)
        assert result[2][0].source == DateSource.PROPAGATED

    def test_propagation_stops_at_new_date(self):
        pages = [
            _make_page("Date of Service: 03/15/2024\nVisit 1", page_number=1),
            _make_page("No date content here", page_number=2),
            _make_page("Date of Service: 03/20/2024\nVisit 2", page_number=3),
            _make_page("Follow-up notes continued", page_number=4),
        ]
        result = extract_dates_for_pages(pages)
        assert result[2][0].sort_date() == date(2024, 3, 15)
        assert result[2][0].source == DateSource.PROPAGATED
        assert result[3][0].sort_date() == date(2024, 3, 20)
        assert result[4][0].sort_date() == date(2024, 3, 20)
        assert result[4][0].source == DateSource.PROPAGATED

    def test_no_propagation_before_first_date(self):
        pages = [
            _make_page("Cover page without any dates", page_number=1),
            _make_page("Date of Service: 03/15/2024\nContent", page_number=2),
        ]
        result = extract_dates_for_pages(pages)
        assert 1 not in result
        assert 2 in result

    def test_cross_document_isolation(self):
        """Pages from different documents should NOT propagate to each other."""
        pages = [
            _make_page("Date of Service: 03/15/2024\nDoc A", page_number=1, doc_id="doc-a"),
            _make_page("No date here", page_number=2, doc_id="doc-b"),
        ]
        result = extract_dates_for_pages(pages)
        assert 1 in result
        assert 2 not in result  # Should NOT inherit from doc-a

    def test_relative_date_with_propagation(self):
        """Anchor detection + relative dates + propagation all working together."""
        pages = [
            _make_page(
                "Patient Chart\nAdmission Date: 01/15/2024\nDay 1, 0900\nBedrest",
                page_number=1,
            ),
            _make_page(
                "Day 2\nPatient resting",
                page_number=2,
            ),
            _make_page(
                "Continued nursing notes, assessment stable.",
                page_number=3,
            ),
        ]
        result = extract_dates_for_pages(pages)
        assert 1 in result
        assert 2 in result
        assert 3 in result
        # Page 1 should have the admission date from tier1
        assert result[1][0].sort_date() == date(2024, 1, 15)
        # Page 2 should resolve Day 2 → 01/16/2024
        assert result[2][0].sort_date() == date(2024, 1, 16)
        # Page 3 should propagate from page 2
        assert result[3][0].sort_date() == date(2024, 1, 16)
        assert result[3][0].source == DateSource.PROPAGATED
