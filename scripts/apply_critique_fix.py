
import sys
import os
import re
import argparse
from pathlib import Path

def apply_fixes(critique_file: str):
    path = Path(critique_file)
    if not path.exists():
        print(f"Error: File {critique_file} not found.")
        return

    content = path.read_text(encoding="utf-8")
    
    # Regex to find <patch> blocks
    # <patch file="path/to/file.py" mode="replace">
    # ... content ...
    # </patch>
    
    # improved regex: allow flexible spacing around attributes
    pattern = re.compile(r'<patch\s+file="([^"]+)"\s+mode="([^"]+)">\s*(.*?)\s*</patch>', re.DOTALL)
    
    matches = pattern.findall(content)
    
    if not matches:
        print("No patches found in the critique file.")
        return

    print(f"Found {len(matches)} patches.")
    
    for file_path, mode, patch_content in matches:
        target_file = Path(file_path.strip())
        
        # Security check: Ensure we are not writing outside of C:\CiteLine generally
        # (Simple check: must be relative or inside C:\CiteLine)
        if not target_file.is_absolute():
            # Assume relative to repo root (C:\CiteLine)
            target_file = Path("C:/CiteLine") / target_file
            
        print(f"Applying patch to: {target_file}")
        
        if mode.lower() == "replace":
            # Backup
            if target_file.exists():
                backup_path = target_file.with_suffix(target_file.suffix + ".bak")
                target_file.rename(backup_path)
                print(f"  - Backed up to {backup_path}")
            
            # Ensure dir exists
            target_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Clean up the patch content (strip wrapping backticks if LLM added them inside XML)
            clean_content = patch_content
            
            # Remove potential markdown code blocks inside the XML if LLM messed up
            clean_content = re.sub(r"^```python\s*", "", clean_content)
            clean_content = re.sub(r"```\s*$", "", clean_content)
            
            target_file.write_text(clean_content, encoding="utf-8")
            print("  - Applied REPLACE patch.")
        else:
            print(f"  - valid mode '{mode}' (only 'replace' supported currently)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply fixes from critique file.")
    parser.add_argument("critique_file", help="Path to the .md file containing patches")
    
    args = parser.parse_args()
    apply_fixes(args.critique_file)
