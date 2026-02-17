import pytest
from datetime import date
from packages.shared.models import Page, EventDate, DateKind, DateSource, EventType, Provider, FactKind, PageType
from apps.worker.steps.step06_dates import extract_dates_for_pages
from apps.worker.steps.events.clinical import extract_clinical_events
from apps.worker.steps.step11_gaps import detect_gaps
from packages.shared.models import RunConfig

def _make_page(text: str, page_number: int = 1, doc_id: str = "julia-doc") -> Page:
    return Page(
        page_id=f"test-page-{page_number}",
        source_document_id=doc_id,
        page_number=page_number,
        text=text,
        text_source="embedded_pdf_text",
        page_type=PageType.CLINICAL_NOTE,
    )

def test_julia_discharge_times_0926():
    """Assert that Julia's discharge events exist at specific times on 09/26."""
    text = """
    9/26
    0925   Dr. Davis at bedside. Orders received for discharge.
    1130   Discharge teaching completed with patient and partner.
    1230   Patient discharged home with partner.
    """
    pages = [_make_page(text, page_number=10)]
    dates_map = extract_dates_for_pages(pages)
    
    providers = [Provider(provider_id="p1", detected_name_raw="General Hosp", normalized_name="General Hospital", provider_type="hospital", confidence=100)]
    events, citations, warnings, skipped = extract_clinical_events(pages, dates_map, providers)
    
    # We expect 3 distinct events at different times
    times = sorted([e.date.extensions.get("time") for e in events if e.date and e.date.extensions])
    assert "0925" in times
    assert "1130" in times
    assert "1230" in times
    assert "0000" not in times # Should not default to 0000 when times are present

def test_row_grouping_same_timestamp():
    """Assert that rows with the same timestamp are grouped into one event."""
    text = """
    9/26 0925 Patient awake.
    9/26 0925 Patient denies pain.
    9/26 0925 Repositioned back in bed.
    """
    pages = [_make_page(text)]
    dates_map = extract_dates_for_pages(pages)
    
    providers = [Provider(provider_id="p1", detected_name_raw="General Hosp", normalized_name="General Hospital", provider_type="hospital", confidence=100)]
    events, _, _, _ = extract_clinical_events(pages, dates_map, providers)
    
    # Should be 1 event with 3 facts
    assert len(events) == 1
    assert events[0].date.extensions.get("time") == "0925"
    assert len(events[0].facts) == 3

def test_referenced_prior_event_exclusion():
    """Assert that historical references do not affect summary ranges."""
    text = "9/24 1600 Patient admitted. Previously discharged home on 9/22."
    pages = [_make_page(text)]
    dates_map = extract_dates_for_pages(pages)
    
    providers = [Provider(provider_id="p1", detected_name_raw="General Hosp", normalized_name="General Hospital", provider_type="hospital", confidence=100)]
    events, _, _, _ = extract_clinical_events(pages, dates_map, providers)
    
    # Verify 9/22 is tagged correctly
    ref_events = [e for e in events if e.event_type == EventType.REFERENCED_PRIOR_EVENT]
    assert len(ref_events) >= 1
    assert "9/22" in ref_events[0].facts[0].text
    assert ref_events[0].flags == ["is_reference"]
