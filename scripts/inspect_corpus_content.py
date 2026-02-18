"""
Inspect the first page of all downloaded PDFs in ssa_corpus to categorize them.
"""
import os
from pathlib import Path
from pypdf import PdfReader

def main():
    root = Path("c:/CiteLine/New folder/ssa_corpus")
    files = list(root.rglob("*.pdf"))
    print(f"Found {len(files)} files.")
    
    ssa_count = 0
    immigration_count = 0
    other_count = 0
    
    for p in files:
        try:
            reader = PdfReader(str(p))
            if len(reader.pages) == 0:
                print(f"[EMPTY] {p.name}")
                continue
                
            text = reader.pages[0].extract_text()
            start = text[:300].replace("\n", " ")
            
            is_ssa = "Social Security" in start or "Commissioner" in start or "405(g)" in start
            is_imm = "Homeland Security" in start or "8 U.S.C" in start or "Immigration" in start
            
            if is_ssa:
                ssa_count += 1
                print(f"[SSA] {p.name}")
            elif is_imm:
                immigration_count += 1
                print(f"[IMMIGRATION] {p.name}")
            else:
                other_count += 1
                print(f"[OTHER] {p.name} | {start}")
                
        except Exception as e:
            print(f"[ERROR] {p.name}: {e}")

    print("-" * 30)
    print(f"Total: {len(files)}")
    print(f"SSA: {ssa_count}")
    print(f"Immigration: {immigration_count}")
    print(f"Other: {other_count}")

if __name__ == "__main__":
    main()
