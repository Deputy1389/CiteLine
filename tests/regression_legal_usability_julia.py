import os
import sys
import pytest
from packages.shared.models import Page, RunConfig, EventType, CaseInfo
from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step02_text_acquire import acquire_text
from apps.worker.steps.step03_classify import classify_pages
from apps.worker.steps.step03a_demographics import extract_demographics
from apps.worker.steps.step06_dates import extract_dates_for_pages
from apps.worker.steps.step07_events import extract_clinical_events
from apps.worker.steps.step09_dedup import deduplicate_events
from apps.worker.steps.step11_gaps import detect_gaps
from apps.worker.steps.events.legal_usability import improve_legal_usability
from apps.worker.steps.step12_export import _date_str

def test_julia_legal_usability_regression():
    print("🚀 Starting Julia Morales Legal Usability Regression...")
    
    pdf_paths = [
        "c:/CiteLine/testdata/eval_06_julia_day1.pdf",
        "c:/CiteLine/testdata/eval_07_julia_day2.pdf",
        "c:/CiteLine/testdata/eval_08_julia_day3.pdf"
    ]
    
    # Check data
    for p in pdf_paths:
        if not os.path.exists(p):
            pytest.skip(f"Missing test data: {p}")

    config = RunConfig(max_pages=100)
    all_pages = []
    
    # 1-2. Ingest
    for pdf_path in pdf_paths:
        doc_id = os.path.basename(pdf_path)
        pages, _ = split_pages(pdf_path, doc_id, page_offset=len(all_pages), max_pages=100)
        pages, _, _ = acquire_text(pages, pdf_path)
        all_pages.extend(pages)

    # 3. Classify
    all_pages, _ = classify_pages(all_pages)
    
    # 6. Dates
    dates = extract_dates_for_pages(all_pages)
    
    # 7. Events
    providers = []
    events, _, _, _ = extract_clinical_events(all_pages, dates, providers)
    
    # 9. Consolidation (Current Step 9)
    events, _ = deduplicate_events(events)
    
    # 11. Gaps
    events, gaps, _ = detect_gaps(events, config)
    
    # --- LEGAL USABILITY PASS ---
    print(f"Before usability pass: {len(events)} events")
    refined_events = improve_legal_usability(events)
    print(f"After usability pass: {len(refined_events)} events")

    # ASSERTIONS
    
    # Target count: 10-35
    assert 10 <= len(refined_events) <= 45, f"Event count {len(refined_events)} outside target 10-45"

    has_pain_1900 = False
    has_emesis_2030 = False
    has_discharge_1230 = False
    has_split_admission = False
    contains_0000 = False
    reference_in_admission = False

    for e in refined_events:
        d_str = _date_str(e)
        facts_text = " ".join(f.text for f in e.facts)
        
        if "09/24" in d_str and "1900" in d_str and "pain 9/10" in facts_text.lower():
            has_pain_1900 = True
            
        if "09/24" in d_str and "2030" in d_str and "emesis" in facts_text.lower():
            has_emesis_2030 = True
            
        if "09/26" in d_str and "1230" in d_str and e.event_type == EventType.HOSPITAL_DISCHARGE:
            has_discharge_1230 = True
            
        if e.extensions and "legal_section" in e.extensions:
            has_split_admission = True
            
        if "0000" in d_str:
            contains_0000 = True
            
        # Check historical references inside admission
        if e.event_type == EventType.HOSPITAL_ADMISSION:
            if "9/22" in facts_text:
                reference_in_admission = True

    assert has_pain_1900, "Missing 09/24 1900 pain event"
    assert has_emesis_2030, "Missing 09/24 2030 emesis event"
    assert has_discharge_1230, "Missing 09/26 1230 discharge event"
    assert has_split_admission, "Admission events were not split into sections"
    assert not contains_0000, "Found '0000' in timestamp display (should be 'time not documented')"
    assert not reference_in_admission, "Historical 9/22 reference still present in Hospital Admission event"

    print("✅ All usability invariants preserved.")

if __name__ == "__main__":
    test_julia_legal_usability_regression()
