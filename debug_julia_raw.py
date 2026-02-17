import os
import sys
import json
from datetime import date

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from packages.shared.models import RunConfig
from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step02_text_acquire import acquire_text
from apps.worker.steps.step03_classify import classify_pages
from apps.worker.steps.step03a_demographics import extract_demographics
from apps.worker.steps.step06_dates import extract_dates_for_pages
from apps.worker.steps.step07_events import extract_clinical_events, extract_discharge_events
from apps.worker.steps.step12_export import _date_str, generate_executive_summary

def debug_raw():
    pdf_paths = [
        "c:/CiteLine/testdata/eval_06_julia_day1.pdf",
        "c:/CiteLine/testdata/eval_07_julia_day2.pdf",
        "c:/CiteLine/testdata/eval_08_julia_day3.pdf"
    ]
    
    all_pages = []
    for pdf_path in pdf_paths:
        doc_id = os.path.basename(pdf_path)
        pages, _ = split_pages(pdf_path, doc_id, page_offset=len(all_pages))
        pages, _, _ = acquire_text(pages, pdf_path)
        all_pages.extend(pages)

    all_pages, _ = classify_pages(all_pages)
    patient, _ = extract_demographics(all_pages)
    dates = extract_dates_for_pages(all_pages, anchor_year_hint=2016)
    
    print("--- EMITTED EVENTS DEBUG ---")
    all_events = []
    
    clin_events, _, _, _ = extract_clinical_events(all_pages, dates, [], {})
    all_events.extend(clin_events)
    print(f"Extracted {len(clin_events)} clinical events")
    
    ds_events, _, _, _ = extract_discharge_events(all_pages, dates, [], {})
    all_events.extend(ds_events)
    print(f"Extracted {len(ds_events)} discharge summary events")
    
    # Filter to discharge types
    dis_events = [e for e in all_events if e.event_type.value in ("hospital_discharge", "discharge")]
    print(f"Total discharge-related events: {len(dis_events)}")
    
    for e in dis_events:
        d_str = _date_str(e)
        print(f"[{d_str}] TYPE={e.event_type.value} TEXT={e.facts[0].text[:80] if e.facts else 'NO FACTS'}...")

    summary = generate_executive_summary(all_events, "Julia Morales")
    print("\n--- SUMMARY ---")
    print(summary)

if __name__ == "__main__":
    debug_raw()
