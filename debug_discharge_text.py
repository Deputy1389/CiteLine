
import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step02_text_acquire import acquire_text

def debug_text():
    pdf_path = "c:/CiteLine/testdata/eval_08_julia_day3.pdf"
    doc_id = os.path.basename(pdf_path)
    pages, warns = split_pages(pdf_path, doc_id, page_offset=0, max_pages=100)
    pages, ocr_count, warns = acquire_text(pages, pdf_path)
    
    print(f"--- RAW TEXT DUMP FOR {doc_id} ---")
    for p in pages:
        print(f"
--- PAGE {p.page_number} (Local {p.page_number}) ---")
        lines = p.text.splitlines()
        for i, line in enumerate(lines):
            line_clean = line.strip()
            if not line_clean: continue
            
            indicators = []
            if "9/26" in line_clean: indicators.append("DATE[9/26]")
            if "0925" in line_clean: indicators.append("TIME[0925]")
            if "1130" in line_clean: indicators.append("TIME[1130]")
            if "1230" in line_clean: indicators.append("TIME[1230]")
            if "Smyth" in line_clean: indicators.append("NAME[Smyth]")
            if "Reyes" in line_clean: indicators.append("NAME[Reyes]")
            
            ind_str = " | ".join(indicators)
            prefix = f"[{ind_str}] " if indicators else ""
            print(f"{i:3}: {prefix}{line_clean}")

if __name__ == "__main__":
    debug_text()
