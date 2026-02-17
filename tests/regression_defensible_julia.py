import pytest
import os
from pathlib import Path
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

def test_julia_defensible_chronology_regression():
    """
    Asserts:
    - Extracted patient name == “Julia Morales”
    - Author attribution for RNs (T. Smyth, M. Reyes)
    - Bullet completeness (no fragments)
    - Point citations for 09/26 discharge
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
    
    # Ingest
    for pdf_path in pdf_paths:
        doc_id = os.path.basename(pdf_path)
        pages, _ = split_pages(pdf_path, doc_id, page_offset=len(all_pages), max_pages=100)
        pages, _, _ = acquire_text(pages, pdf_path)
        all_pages.extend(pages)

    # 3. Classify
    all_pages, _ = classify_pages(all_pages)
    
    # 3a. Demographics
    patient, _ = extract_demographics(all_pages)
    assert patient.name == "Julia Morales"
    assert patient.mrn == "123-456-78"

    # 6. Dates
    dates = extract_dates_for_pages(all_pages)
    
    # 7. Events
    providers = []
    page_provider_map = {}
    events, citations, _, _ = extract_clinical_events(all_pages, dates, providers, page_provider_map)
    
    # 9. Consolidation
    events, _ = deduplicate_events(events)
    
    # 11. Gaps
    events, _, _ = detect_gaps(events, config)
    
    # 11a. Usability Pass
    refined_events = improve_legal_usability(events)
    
    # ASSERTIONS
    
    has_smyth = False
    has_reyes = False
    discharge_cited_correctly = False
    no_fragments = True

    for e in refined_events:
        d_str = _date_str(e)
        facts_text = " ".join(f.text for f in e.facts)
        
        # Task 2: Author attribution
        if e.author_name == "T. Smyth" and e.author_role == "RN":
            has_smyth = True
        if e.author_name == "M. Reyes" and e.author_role == "RN":
            has_reyes = True
            
        # Task 3: Bullet integrity
        for f in e.facts:
            if f.text.strip().lower().endswith(("treated with", "conc", "with", "the")):
                no_fragments = False
                print(f"DEBUG: Found fragment: {f.text}")

        # Task 4: Point Citations for 09/26 1230 Discharge
        if "09/26" in d_str and "1230" in d_str and e.event_type == EventType.HOSPITAL_DISCHARGE:
            # Should only cite eval_08_julia_day3.pdf (page index > 20 globally)
            # Find associated citations
            event_cits = [c for c in citations if c.citation_id in e.citation_ids]
            doc_ids = set(c.source_document_id for c in event_cits)
            if len(doc_ids) == 1 and "eval_08_julia_day3.pdf" in list(doc_ids)[0]:
                discharge_cited_correctly = True
            else:
                print(f"DEBUG: Discharge cites: {doc_ids}")

    assert has_smyth, "Missing T. Smyth, RN attribution"
    assert has_reyes, "Missing M. Reyes, RN attribution"
    assert no_fragments, "Found truncated/fragmented bullets"
    assert discharge_cited_correctly, "09/26 1230 Discharge cites multiple or incorrect PDFs"

if __name__ == "__main__":
    test_julia_defensible_chronology_regression()
