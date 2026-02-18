"""
Generate a 'Critique Packet' for a given Run ID.
Bundles Source Text (by page) and Extracted Events (chronological) into a single Markdown file
suitable for LLM analysis or manual review.

Usage:
    python scripts/generate_critique_prompt.py <run_id> [--limit N]
"""
import sys
import os
import argparse
from pathlib import Path
from sqlalchemy.orm import joinedload

# Add project root to path
root = Path(__file__).resolve().parent.parent
sys.path.append(str(root))

from packages.db.database import get_session
from packages.db.models import Run, Page, Event

def generate_prompt(run_id: str, limit: int = None, output_path: str = None):
    print(f"Generating critique prompt for Run ID: {run_id} (Limit: {limit} pages)")
    
    with get_session() as session:
        # Fetch Run
        run = session.query(Run).filter(Run.id == run_id).first()
        if not run:
            print(f"Error: Run {run_id} not found.")
            return

        # Fetch Pages (Source Text)
        query = session.query(Page)\
            .filter(Page.run_id == run_id)\
            .order_by(Page.page_number)
            
        if limit:
            query = query.limit(limit)
            
        pages = query.all()
            
        if not pages:
            print("Warning: No pages found for this run.")

        # Fetch Events (Extraction Results)
        events = session.query(Event)\
            .filter(Event.run_id == run_id)\
            .all()

        # Helper to parse date_json into sortable tuple and string
        def parse_date(date_json):
            d = date_json or {}
            val = d.get('value')
            
            # 1. Full Date
            if val:
                if isinstance(val, str):
                    # YYYY-MM-DD
                    parts = val.split('-')
                    if len(parts) == 3:
                        return (int(parts[0]), int(parts[1]), int(parts[2])), val
                elif isinstance(val, dict):
                    # DateRange
                    start = val.get('start')
                    if start:
                        parts = start.split('-')
                        if len(parts) == 3:
                             return (int(parts[0]), int(parts[1]), int(parts[2])), start
            
            # 2. Relative Day
            rd = d.get('relative_day')
            if rd is not None:
                return (9000, 0, rd), f"Day {rd}"

            # 3. Partial Date
            pm = d.get('partial_month')
            pd = d.get('partial_day')
            if pm and pd:
                 return (9999, int(pm), int(pd)), f"????-{int(pm):02d}-{int(pd):02d}"

            # 4. Fallack
            return (9999, 13, 32), "????-??-??"

        # Sort events manually
        def event_sort_key(e):
            sort_tuple, _ = parse_date(e.date_json)
            return sort_tuple
        
        events.sort(key=event_sort_key)

        # Build Content ONLY while session is open to avoid DetachedInstanceError
        content = []
        content.append(f"# Critique Request for Run `{run_id}`")
        if run:
            content.append(f"**Date:** {run.created_at}")
            content.append(f"**Matter ID:** {run.matter_id}")
        content.append("\n---\n")

        # Section 1: Source Text
        content.append("## PART 1: SOURCE TEXT")
        content.append("Below is the raw OCR/Text extracted from the document, chunked by page.\n")
        
        for p in pages:
            content.append(f"### Page {p.page_number}")
            text = p.text.strip() if p.text else "[NO TEXT]"
            content.append("```text")
            content.append(text)
            content.append("```\n")

        content.append("\n---\n")

        # Section 2: Extracted Events
        content.append("## PART 2: EXTRACTED CHRONOLOGY")
        content.append("Below are the events extracted by the pipeline, ordered chronologically.\n")

        for e in events:
            # Format Date
            _, date_str = parse_date(e.date_json)
            
            # Format Facts
            facts_raw = e.facts_json or []
            facts_text = []
            for f in facts_raw:
                if isinstance(f, dict):
                    facts_text.append(f.get('text', str(f)))
                else:
                    facts_text.append(str(f))
            payload = "; ".join(facts_text)
            
            # Format Sources
            pages_ref = e.source_page_numbers_json or []
            
            content.append(f"- **{date_str}** [{e.event_type}]: {payload}")
            if pages_ref:
                content.append(f"  - *Source Pages: {pages_ref}*")
            content.append("")

        content.append("\n---\n")

        # Section 3: Instructions
        content.append("## PART 3: INSTRUCTIONS")
        content.append("You are a QA system. Your goal is to identify missing events or errors in the extracted chronology.")
        content.append("1. Compare the Source Text with the Extracted Chronology.")
        content.append("2. Identify any missing dates, significant medical events, or incorrect details.")
        content.append("3. If you find a systematic error (e.g. missing events due to a specific regex failure), provide a code patch.")
        content.append("4. **CRITICAL**: Provide fixes in the following XML format so they can be automatically applied:")
        content.append("")
        content.append("```xml")
        content.append('<patch file="path/to/file.py" mode="replace">')
        content.append("# ... new content for the entire file or function ...")
        content.append("</patch>")
        content.append("```")
        content.append("")
        content.append("If no code changes are needed, just list the data errors.")

    # Output (outside session is fine now that strings are built)
    final_text = "\n".join(content)
    
    if output_path:
        out_file = Path(output_path)
    else:
        out_file = Path(f"critique_{run_id}.md")
        
    out_file.write_text(final_text, encoding="utf-8")
    print(f"Critique packet saved to: {out_file.absolute()}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate critique prompt for a run.")
    parser.add_argument("run_id", help="The Run ID to process")
    parser.add_argument("--limit", type=int, help="Limit number of pages to include")
    
    args = parser.parse_args()
    generate_prompt(args.run_id, limit=args.limit)
