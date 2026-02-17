import pytest
import os
from pathlib import Path
from packages.shared.models import Page, RunConfig, EventType
from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step02_text_acquire import acquire_text
from apps.worker.steps.step03_classify import classify_pages
from apps.worker.steps.step06_dates import extract_dates_for_pages
from apps.worker.steps.events.clinical import extract_clinical_events
from apps.worker.steps.step09_dedup import deduplicate_events
from apps.worker.steps.step12_export import _date_str

def test_julia_signal_filtering():
    """
    Regression test for signal filtering and event consolidation using Julia Morales PDFs.
    """
    pdf_paths = [
        "c:/CiteLine/testdata/eval_06_julia_day1.pdf",
        "c:/CiteLine/testdata/eval_07_julia_day2.pdf",
        "c:/CiteLine/testdata/eval_08_julia_day3.pdf"
    ]
    
    # Ensure files exist
    for p in pdf_paths:
        if not os.path.exists(p):
            pytest.skip(f"Test data not found: {p}")

    config = RunConfig(max_pages=100)
    all_pages = []
    
    # 1-2. Split & Acquire Text
    for pdf_path in pdf_paths:
        doc_id = os.path.basename(pdf_path)
        pages, warns = split_pages(pdf_path, doc_id, page_offset=len(all_pages), max_pages=100)
        pages, ocr_count, warns = acquire_text(pages, pdf_path)
        all_pages.extend(pages)

    # 3. Classify
    all_pages, _ = classify_pages(all_pages)
    
    # 6. Dates
    dates = extract_dates_for_pages(all_pages)
    
    # 7. Events
    providers = []
    page_provider_map = {}
    events, citations, warns, skipped = extract_clinical_events(all_pages, dates, providers, page_provider_map)
    
    # 9. Consolidation & Signal Filtering (Critical Step)
    consolidated_events, _ = deduplicate_events(events)
    
    # Assertions on event count (15-40 events)
    assert 15 <= len(consolidated_events) <= 60, f"Event count {len(consolidated_events)} out of range (15-60)"

    # Check for presence of required clinical signals
    has_pain_1900 = False
    has_emesis_2030 = False
    has_discharge_1230 = False
    
    # Check for absence of scaffolding
    contains_scaffolding = False
    
    for e in consolidated_events:
        d_str = _date_str(e)
        facts_text = " ".join(f.text for f in e.facts)
        
        if "09/24" in d_str and "1900" in d_str and "pain 9/10" in facts_text.lower():
            has_pain_1900 = True
            
        if "09/24" in d_str and "2030" in d_str and "emesis" in facts_text.lower():
            has_emesis_2030 = True
            
        if "09/26" in d_str and "1230" in d_str and e.event_type == EventType.HOSPITAL_DISCHARGE:
            has_discharge_1230 = True
            
        if any(p in facts_text for p in ["E=R Thigh", "Date/Time:", "Vital Signs Record"]):
            print(f"DEBUG: Scaffolding found in event: {d_str} {e.event_type} - {facts_text[:100]}...")
            contains_scaffolding = True

    assert has_pain_1900, "Missing 09/24 1900 pain 9/10 event"
    assert has_emesis_2030, "Missing 09/24 2030 emesis event"
    assert has_discharge_1230, "Missing 09/26 1230 discharge event"
    assert not contains_scaffolding, "Timeline contains boilerplate/scaffolding text"

if __name__ == "__main__":
    test_julia_signal_filtering()
