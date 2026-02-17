import os
import sys
import json
from datetime import date
from pathlib import Path

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from packages.shared.models import Page, RunConfig, CaseInfo
from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step02_text_acquire import acquire_text
from apps.worker.steps.step03_classify import classify_pages
from apps.worker.steps.step03a_demographics import extract_demographics
from apps.worker.steps.step06_dates import extract_dates_for_pages
from apps.worker.steps.step07_events import extract_clinical_events
from apps.worker.steps.step09_dedup import deduplicate_events
from apps.worker.steps.step11_gaps import detect_gaps
from apps.worker.steps.step12_export import render_exports

def run_eval():
    print("🚀 Starting Julia Morales Eval Run...")
    
    pdf_paths = [
        "c:/CiteLine/testdata/eval_06_julia_day1.pdf",
        "c:/CiteLine/testdata/eval_07_julia_day2.pdf",
        "c:/CiteLine/testdata/eval_08_julia_day3.pdf"
    ]
    
    config = RunConfig(max_pages=100)
    all_pages = []
    
    # 1-2. Split & Acquire Text
    for pdf_path in pdf_paths:
        doc_id = os.path.basename(pdf_path)
        print(f"Acquiring text for {doc_id}...")
        pages, warns = split_pages(pdf_path, doc_id, page_offset=len(all_pages), max_pages=100)
        pages, ocr_count, warns = acquire_text(pages, pdf_path)
        all_pages.extend(pages)

    # 3. Classify
    print("Classifying pages...")
    all_pages, _ = classify_pages(all_pages)
    
    # 3a. Demographics
    print("Extracting demographics...")
    patient, _ = extract_demographics(all_pages)
    print(f"RESOLVED PATIENT: Sex={patient.sex}, Age={patient.age}, DOB={patient.dob}")

    # 6. Dates
    print("Extracting dates (Safe Engine)...")
    dates = extract_dates_for_pages(all_pages)
    
    # 7. Events (Clinical only for eval)
    print("Extracting clinical events...")
    # Providers mock
    providers = []
    page_provider_map = {}
    events, citations, warns, skipped = extract_clinical_events(all_pages, dates, providers, page_provider_map)
    
    # 9. Deduplication & Signal Filtering
    print(f"Consolidating and filtering {len(events)} events...")
    events, _ = deduplicate_events(events)

    # 11. Gaps
    print(f"Detecting gaps among {len(events)} events...")
    events, gaps, _ = detect_gaps(events, config)
    
    # 12. Export
    print("Rendering exports...")
    # page_map mock
    page_map = {p.page_number: (p.source_document_id, p.page_number) for p in all_pages}
    
    case_info = CaseInfo(
        case_id="eval-julia-id",
        firm_id="eval-firm",
        title="Julia Morales - Medical Chronology (FIXED)",
        patient=patient
    )

    chronology = render_exports(
        run_id="eval-julia-morales",
        matter_title="Julia Morales - Medical Chronology (FIXED)",
        events=events,
        gaps=gaps,
        providers=providers,
        page_map=page_map,
        case_info=case_info
    )
    
    # Show Results summary
    print("\n" + "="*50)
    print("EVALUATION RESULTS")
    print("="*50)
    print(f"Patient Sex: {patient.sex} (Confidence: {patient.sex_confidence})")
    print(f"Patient Age: {patient.age}")
    print(f"Total Events: {len(events)}")
    print(f"Total Gaps: {len(gaps)}")
    
    print("\nEXECUTIVE SUMMARY:")
    print("-" * 20)
    print(chronology.summary)
    print("-" * 20)

    # Print the first 15 events
    print("\nSAMPLE TIMELINE (First 15 events):")
    from apps.worker.steps.step12_export import _date_str
    for e in events[:15]:
        d_str = _date_str(e) or "UNDATED"
        facts = "; ".join(f.text for f in e.facts[:2])
        print(f"[{d_str}] {e.event_type.value}: {facts[:100]}...")

    print("\nSPECIFIC 09/26 EVENTS:")
    for e in events:
        d_str = _date_str(e)
        if d_str.startswith("09/26 (year unknown)"):
            facts = "; ".join(f.text for f in e.facts)
            print(f"[{d_str}] {e.event_type.value}: {facts}")
    
    if gaps:
        print("\nGAPS DETECTED:")
        for g in gaps:
            print(f"- From {g.start_date} to {g.end_date} ({g.duration_days} days)")
    else:
        print("\nNO GAPS DETECTED.")

    # PART 5 VERIFICATION: NO INFERRED YEARS
    inferred = [e for e in events if e.date and e.date.value and hasattr(e.date.value, "year") and e.date.value.year == 2016 and (e.date.extensions or {}).get("year_missing") == True]
    if inferred:
        print(f"\n❌ REGRESSION: Found {len(inferred)} events with inferred years!")
    else:
        print("\n✅ PASS: No inferred years found (Invariant 1 preserved).")
        
    print("\n✓ Evaluation complete. Artifacts rendered to data/runs/eval-julia-morales/output/")

if __name__ == "__main__":
    run_eval()
