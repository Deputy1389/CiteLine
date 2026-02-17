import pytest
from datetime import date
from packages.shared.models import (
    DateKind,
    DateSource,
    EventDate,
    EventType,
    Page,
    PageType,
    Provider,
)
from apps.worker.steps.events.clinical import extract_clinical_events

def _make_page(text: str, page_number: int = 1, page_type=PageType.CLINICAL_NOTE):
    return Page(
        page_id=f"test-page-{page_number}",
        source_document_id="test-doc",
        page_number=page_number,
        text=text,
        text_source="embedded_pdf_text",
        page_type=page_type,
    )

def _make_date(year, month, day, source=DateSource.TIER1):
    return EventDate(
        kind=DateKind.SINGLE,
        value=None,
        source=source,
        partial_month=month,
        partial_day=day,
        extensions={
            "partial_date": True,
            "partial_month": month,
            "partial_day": day,
            "year_missing": True,
        },
    )

def test_clinical_block_fallback_picks_min_date_for_procedure():
    """
    Test that a clinical block identified as a procedure (which triggers fallback 
    because 'procedure' is not eventworthy for flowsheet) picks the earliest date.
    """
    p1 = _make_page("Chief Complaint: Evaluation of knee issue.", page_number=1)
    d1 = _make_date(2024, 9, 24)
    
    p2 = _make_page("Assessment: Surgery performed.", page_number=2)
    d2 = _make_date(2024, 9, 25)
    
    pages = [p1, p2]
    dates = {1: [d1], 2: [d2]}
    providers = [Provider(
        provider_id="prov1", 
        detected_name_raw="Dr. Smith", 
        normalized_name="Dr. Smith", 
        confidence=100
    )]
    
    events, citations, warnings, skipped = extract_clinical_events(pages, dates, providers)
    
    # etype should be PROCEDURE
    proc_events = [e for e in events if e.event_type == EventType.PROCEDURE]
    assert len(proc_events) >= 1
    
    # It should have picked d1 (09/24)
    evt_date = proc_events[0].date
    assert evt_date.extensions["partial_day"] == 24

def test_clinical_block_fallback_picks_min_date_for_triage():
    """
    Test that a clinical block identified as ER_VISIT picks the earliest date.
    We use 'triage' in a recognized header to trigger fallback facts.
    """
    p1 = _make_page("Chief Complaint: Triage for checkup.", page_number=1)
    d1 = _make_date(2024, 9, 24)
    
    p2 = _make_page("Assessment: Patient seen in ER.", page_number=2)
    d2 = _make_date(2024, 9, 25)
    
    pages = [p1, p2]
    dates = {1: [d1], 2: [d2]}
    providers = [Provider(
        provider_id="prov1", 
        detected_name_raw="Dr. Smith", 
        normalized_name="Dr. Smith", 
        confidence=100
    )]
    
    events, citations, warnings, skipped = extract_clinical_events(pages, dates, providers)
    
    er_events = [e for e in events if e.event_type == EventType.ER_VISIT or e.event_type == EventType.HOSPITAL_ADMISSION]
    assert len(er_events) >= 1
    # It should have picked d1 (09/24)
    evt_date = er_events[0].date
    assert evt_date.extensions["partial_day"] == 24
