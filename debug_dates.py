
import logging
import sys
import os
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.append(os.getcwd())

from packages.shared.models import SourceDocument, RunStatus, DocumentType
from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step02_text_acquire import acquire_text
from apps.worker.steps.step03_classify import classify_pages
from apps.worker.steps.step06_dates import extract_dates_for_pages

def debug_dates():
    # File to debug
    filename = "eval_02_millie_day1.pdf"
    filepath = os.path.join("testdata", filename)
    
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    print(f"Debugging dates for: {filename}")
    
    # Mock document
    doc = SourceDocument(
        document_id="debug_millie_02",
        filename=filename,
        original_path=filepath,
        status=RunStatus.RUNNING,
        case_id="debug_case",
        corpus_name="debug_corpus",
        upload_date=datetime.now(),
        file_size_bytes=os.path.getsize(filepath),
        sha256="dummy_sha",
        bytes=0
    )

    # Step 1: Split
    print("Step 1: Splitting...")
    pages, warnings = split_pages(filepath, doc.document_id, 0, 100)
    
    # Step 2: Acquire Text
    print("Step 2: Acquiring Text...")
    pages, count, warnings = acquire_text(pages, filepath)
    
    # Print first page text to see what we are dealing with
    if pages:
        print("\n--- Text Analysis ---")
        for i, p in enumerate(pages):
            print(f"-- Page {i+1} --")
            print(p.text[:1000])  # First 1000 chars
            print("...")
            print("-" * 20)

    # Step 3: Classify
    print("Step 3: Classifying...")
    pages, warnings = classify_pages(pages)
    
    # Step 6: Dates
    print("Step 6: Extracting Dates...")
    dates_map = extract_dates_for_pages(pages)
    
    print("\n--- Date Extraction Results ---")
    for page in pages:
        page_dates = dates_map.get(page.page_number, [])
        print(f"Page {page.page_number} ({page.page_type}): Found {len(page_dates)} dates")
        for d in page_dates:
            print(f"  - Value: {d.value}, Relative: {d.relative_day} (Source: {d.source})")
            
if __name__ == "__main__":
    debug_dates()
