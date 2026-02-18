"""
Generate Synthetic Training Data (Input -> Output Pairs).
Can ingest MIMIC-IV notes (or any text files) and rewrite them using the Gold Standard Style.

Usage: 
    python scripts/generate_training_data.py --input_dir "path/to/mimic/notes" --output_dir "training_data"
    python scripts/generate_training_data.py --file "c:/CiteLine/testdata/eval_01_amfs_packet.pdf"
"""
import os
import sys
import json
import argparse
import glob
from pathlib import Path
from openai import OpenAI

# Add project root
sys.path.append(os.getcwd())

from pypdf import PdfReader

STYLE_GUIDE_PATH = Path("c:/CiteLine/gold_standard_style.txt")

def read_file(path: Path) -> str:
    """Read text from PDF or TXT."""
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        text = []
        # Cap at 20 pages to avoid huge tokens for demo
        for i, page in enumerate(reader.pages[:20]):
            text.append(page.extract_text() or "")
        return "\n".join(text)
    else:
        return path.read_text(encoding="utf-8", errors="ignore")

def load_style_guide():
    if not STYLE_GUIDE_PATH.exists():
        return "Write a professional medical chronology for a legal brief."
    return STYLE_GUIDE_PATH.read_text(encoding="utf-8")

def generate_gold_summary(input_text: str, client: OpenAI) -> str:
    """Ask LLM to summarize the input using the Style Guide."""
    style_prompt = load_style_guide()
    
    prompt = f"""
    ROLE: You are an expert paralegal at a high-end law firm.
    TASK: Summarize the provided medical records into a "Statement of Facts" for a legal brief.
    
    STYLE GUIDE (Follow strictly):
    {style_prompt}
    
    INSTRUCTIONS:
    - Use the exact tone and formatting usage in the Style Guide.
    - Focus on functional limitations and timeline.
    - Cite the "record" as "(Rec [Page])" if page numbers are inferred, or just "(Record)".
    
    INPUT RECORDS:
    {input_text[:15000]} 
    """
    # Truncate to 15k chars for safety and cost
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a legal medical summarizer."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", help="Directory containing .txt or .pdf files")
    parser.add_argument("--file", help="Single file to process")
    parser.add_argument("--output_dir", default="training_data", help="Where to save JSON pairs")
    parser.add_argument("--key", help="OpenAI API Key")
    args = parser.parse_args()
    
    if args.key:
        os.environ["OPENAI_API_KEY"] = args.key
        
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set.")
        return

    client = OpenAI(api_key=api_key)
    
    files = []
    if args.file:
        files.append(Path(args.file))
    elif args.input_dir:
        files.extend(list(Path(args.input_dir).glob("*.txt")))
        files.extend(list(Path(args.input_dir).glob("*.pdf")))
        
    if not files:
        print("No files found.")
        return
        
    out_dir = Path(args.output_dir)
    out_dir.mkdir(exist_ok=True)
    
    print(f"Processing {len(files)} files...")
    
    for f in files:
        try:
            print(f"Reading {f.name}...", flush=True)
            input_text = read_file(f)
            if len(input_text) < 100:
                print(f"Skipping {f.name} (too short)", flush=True)
                continue
                
            print(f"Generating Summary (using Style Guide)...", flush=True)
            output_text = generate_gold_summary(input_text, client)
            
            # Save Pair
            pair = {
                "source_file": f.name,
                "input_text": input_text,
                "output_summary": output_text,
                "style_guide_used": True
            }
            
            out_path = out_dir / f"{f.stem}_training_pair.json"
            out_path.write_text(json.dumps(pair, indent=2), encoding="utf-8")
            print(f"Saved {out_path}", flush=True)
            
        except Exception as e:
            print(f"Failed {f.name}: {e}", flush=True)

if __name__ == "__main__":
    main()
