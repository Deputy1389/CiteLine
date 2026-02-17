import os
import sys
import pytest
import re
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
from apps.worker.steps.step12_export import _date_str, generate_executive_summary

def test_julia_a_plus_plus_regression():
    print("🚀 Starting Julia Morales A++ Legal Usability Regression...")
    
    pdf_paths = [
        "c:/CiteLine/testdata/eval_06_julia_day1.pdf",
        "c:/CiteLine/testdata/eval_07_julia_day2.pdf",
        "c:/CiteLine/testdata/eval_08_julia_day3.pdf"
    ]
    
    for p in pdf_paths:
        if not os.path.exists(p):
            pytest.skip(f"Missing test data: {p}")

    config = RunConfig(max_pages=100)
    all_pages = []
    
    for pdf_path in pdf_paths:
        doc_id = os.path.basename(pdf_path)
        pages, _ = split_pages(pdf_path, doc_id, page_offset=len(all_pages), max_pages=100)
        pages, _, _ = acquire_text(pages, pdf_path)
        all_pages.extend(pages)

    # 1. Demographics & Identity Anchoring
    all_pages, _ = classify_pages(all_pages)
    patient, _ = extract_demographics(all_pages)
    
    assert patient.name == "Julia Morales"
    assert patient.mrn == "123-456-78"

    # 6-11. Pipeline
    dates = extract_dates_for_pages(all_pages)
    providers = []
    events, citations, _, _ = extract_clinical_events(all_pages, dates, providers)
    events, _ = deduplicate_events(events)
    events, gaps, _ = detect_gaps(events, config)
    
    # 11a. Usability Pass (Refined)
    refined_events = improve_legal_usability(events)
    
    # 12. Summary Check
    case_info = CaseInfo(case_id="case-123", firm_id="firm-1", title="Julia Morales case", patient=patient)
    summary = generate_executive_summary(refined_events, "Julia Morales - Medical Chronology", case_info=case_info)
    
    assert "Patient (extracted): Julia Morales (MRN 123-456-78)" in summary
    assert "Matter label: Julia Morales" in summary

    # INVARIANTS CHECK
    
    has_stitched_quote = False
    has_correct_smyth = False
    has_correct_reyes = False
    contains_junk = False
    contains_0000 = False
    
    event_count = len(refined_events)
    print(f"Final event count: {event_count}")
    
    for e in refined_events:
        d_str = _date_str(e)
        facts_text = " ".join(f.text for f in e.facts)
        
        if "0000" in d_str:
            contains_0000 = True
            
        # Task 3: Quote stitching
        if "I just can’t move fast enough" in facts_text and "do not know what to do" in facts_text:
            has_stitched_quote = True
            
        # Task 2: Author Attribution
        if "09/24" in d_str and "2200" in d_str:
            print(f"DEBUG 09/24 2200: author={e.author_name} role={e.author_role}")
            if e.author_name in ("T. Smyth", "T. Smith") and e.author_role == "RN":
                has_correct_smyth = True
        
        if "09/26" in d_str and "1230" in d_str:
            if e.author_name == "M. Reyes" and e.author_role == "RN":
                has_correct_reyes = True

        # Task 4: Point Citations for Discharge
        if "09/26" in d_str and "1230" in d_str:
            # Check citationids
            event_cits = [c for c in citations if c.citation_id in e.citation_ids]
            for c in event_cits:
                assert "eval_08_julia_day3.pdf" in c.source_document_id

        # Junk check
        for f in e.facts:
            t = f.text.upper()
            if any(j in t for j in ["SEE NURSING NOTES", "APPEARANCE OF URINE", "FEMALES: LMP"]):
                contains_junk = True
                print(f"DEBUG: Junk found: {f.text}")
            if "NAUSEA/VOMITI" in t and not t.endswith("NG"):
                contains_junk = True
                print(f"DEBUG: Junk found: {f.text}")

    assert 10 <= event_count <= 40
    assert has_stitched_quote
    assert has_correct_smyth
    assert has_correct_reyes
    assert not contains_junk
    assert not contains_0000

    print("✅ All A++ Legal Usability Invariants Preserved.")

if __name__ == "__main__":
    test_julia_a_plus_plus_regression()
