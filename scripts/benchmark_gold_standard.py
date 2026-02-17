"""
Generate 'Gold Standard' chronologies using OpenAI GPT-4o.
Usage: python scripts/benchmark_gold_standard.py [run_id]

If run_id is not provided, it picks the first 'pending' or 'success' run from the Benchmark matter.
Requires OPENAI_API_KEY environment variable.
"""
import os
import sys
import json
import argparse
from pathlib import Path
from openai import OpenAI

# Add project root to path
sys.path.append(os.getcwd())

from packages.db.database import get_session
from packages.db.models import Run, SourceDocument
from packages.shared.storage import get_upload_path
from apps.worker.steps.step02_text_acquire import acquire_text
from apps.worker.steps.step01_page_split import split_pages

def extract_text_from_run(run_id: str, session) -> str:
    """Extract full text from the source document of a run."""
    run = session.query(Run).filter_by(id=run_id).first()
    if not run:
        raise ValueError(f"Run {run_id} not found")
        
    doc = session.query(SourceDocument).filter_by(matter_id=run.matter_id).first() # Simplified: assumes 1 doc per matter for benchmark
    if not doc:
        raise ValueError("No source document found for run")
        
    pdf_path = get_upload_path(doc.id)
    if not pdf_path.exists():
        raise ValueError(f"PDF not found at {pdf_path}")
        
    # Reuse pipeline steps to get text
    # Note: This effectively re-does OCR if needed, but for benchmark likely text-based
    print(f"Extracting text from {doc.filename}...")
    pages, _ = split_pages(str(pdf_path), doc.id, 0, 50) # Cap at 50 pages for cost
    pages, _, _ = acquire_text(pages, str(pdf_path))
    
    full_text = "\n\n".join([p.text for p in pages])
    return full_text

def query_llm(text: str) -> str:
    """Send text to GPT-4o for event extraction."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set.")
        
    client = OpenAI(api_key=api_key)
    
    print("Sending request to OpenAI (GPT-4o)...")
    
    prompt = f"""
    You are a senior paralegal. Extract a medical chronology from the following text.
    Return ONLY a JSON object with a list of events.
    
    Format:
    {{
      "events": [
        {{
          "date": "YYYY-MM-DD",
          "time": "HH:MM", 
          "provider": "Doctor Name",
          "description": "Succinct summary of clinical facts (pain, meds, diagnosis)"
        }}
      ]
    }}
    
    Rules:
    1. Extract specific dates. If partial, use YYYY-MM-01.
    2. Ignore administrative boilerplate (fax headers, etc).
    3. Focus on clinical encounters, symptoms, and orders.
    
    Text:
    {text[:100000]} 
    """
    # Truncate text to ~25k tokens roughly to avoid context limits if huge
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a precise medical data extractor."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    return response.choices[0].message.content

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", nargs="?", help="Run ID to benchmark")
    args = parser.parse_args()
    
    with get_session() as session:
        if args.run_id:
            run = session.query(Run).filter_by(id=args.run_id).first()
        else:
            # Pick a sample run
            # Find the 'Benchmark Law Firm' runs
            run = (
                session.query(Run)
                .join(Run.matter)
                .join(SourceDocument, SourceDocument.matter_id == Run.matter_id) # filtering context
                .first() 
            ) # Just grabbing *any* run for now to test
            
        if not run:
            print("No suitable run found.")
            return
            
        print(f"Benchmarking Run: {run.id}")
        
        try:
            text = extract_text_from_run(run.id, session)
            print(f"Extracted {len(text)} characters.")
            
            gold_standard_json = query_llm(text)
            
            out_path = Path(f"benchmark_gold_{run.id}.json")
            out_path.write_text(gold_standard_json, encoding="utf-8")
            print(f"Saved Gold Standard to {out_path}")
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
