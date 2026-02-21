import pytest
from datetime import date
from packages.shared.models import EventDate, DateKind, DateSource, Event, EventType
from apps.worker.steps.step12_export import _date_str
from apps.worker.steps.step06_dates import extract_dates, extract_dates_for_pages, Page

def test_event_date_sorting():
    # Absolute date
    d1 = EventDate(kind=DateKind.SINGLE, value=date(2023, 1, 1), source=DateSource.TIER1)
    # Positive relative day
    d2 = EventDate(kind=DateKind.SINGLE, relative_day=1, source=DateSource.TIER2)
    # Partial date
    d3 = EventDate(kind=DateKind.SINGLE, partial_month=9, partial_day=24, source=DateSource.TIER2)
    # Unknown/Empty
    d4 = EventDate(kind=DateKind.SINGLE, source=DateSource.TIER2)

    # Sort keys (now include time suffix ' 0000' by default)
    k1 = d1.sort_key() # (0, '2023-01-01 0000')
    k2 = d2.sort_key() # (1, '000001 0000')
    k3 = d3.sort_key() # (2, '09-24 0000')
    k4 = d4.sort_key() # (99, 'UNKNOWN')

    assert k1 == (0, "2023-01-01 0000")
    assert k2 == (1, "000001 0000")
    assert k3 == (2, "09-24 0000")
    assert k4 == (99, "UNKNOWN")

    # Sorted order: Absolute (0) < Relative (1) < Partial (2) < Unknown (99)
    sorted_dates = sorted([d1, d2, d3, d4], key=lambda x: x.sort_key())
    assert sorted_dates == [d1, d2, d3, d4]

def test_date_str_formatting():
    # Test cases for _date_str
    def mock_event(ed):
        return Event(
            event_id="test",
            provider_id="test",
            event_type=EventType.OFFICE_VISIT,
            date=ed,
            confidence=100
        )

    # Absolute
    ed1 = EventDate(kind=DateKind.SINGLE, value=date(2016, 9, 24), source=DateSource.TIER1)
    assert _date_str(mock_event(ed1)) == "2016-09-24 (time not documented)"

    # Relative
    ed2 = EventDate(kind=DateKind.SINGLE, relative_day=2, source=DateSource.TIER2)
    assert _date_str(mock_event(ed2)) == "Date not documented"

    # Partial
    ed3 = EventDate(kind=DateKind.SINGLE, partial_month=9, partial_day=24, source=DateSource.TIER2)
    assert _date_str(mock_event(ed3)) == "Date not documented"

    # Sentinel used to be -924, should now be empty or handled by partial fields
    ed4 = EventDate(kind=DateKind.SINGLE, relative_day=-924, source=DateSource.TIER2)
    assert _date_str(mock_event(ed4)) == "Date not documented"

def test_partial_date_extraction():
    page = Page(
        page_id="p1",
        source_document_id="doc1",
        page_number=1,
        text="Seen on 09/24. Also a note from 01/15/2016.",
        text_source="test"
    )
    
    # Pass 1: Extraction
    extracted = extract_dates(page)
    # items are (EventDate, label)
    dates = [e for e, l in extracted]
    
    # One absolute (2016-01-15), one partial (09/24)
    assert len(dates) == 2
    
    abs_date = next(d for d in dates if d.value == date(2016, 1, 15))
    partial_date = next(d for d in dates if d.partial_month == 9)
    
    assert partial_date.value is None
    assert partial_date.partial_day == 24
    assert partial_date.relative_day is None

def test_partial_date_resolution():
    pages = [
        Page(page_id="p1", source_document_id="doc1", page_number=1, text="Year: 2016", text_source="test"),
        Page(page_id="p1", source_document_id="doc1", page_number=2, text="Visit: 09/24", text_source="test")
    ]
    
    # 2016-01-01 is a placeholder for "Year: 2016" if we had better extraction, 
    # but let's just use anchor_year_hint for this test simplicity.
    
    result = extract_dates_for_pages(pages)
    
    # Page 2 keeps a yearless partial date and should not fabricate a year.
    assert 2 in result
    p2_dates = result[2]
    assert any(d.value is None and d.partial_month == 9 and d.partial_day == 24 for d in p2_dates)
