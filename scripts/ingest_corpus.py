"""
Script to bulk ingest the downloaded ssa_corpus PDFs into Citeline.
For each PDF:
1. Create a persistent SourceDocument record.
2. Copy the file to the local storage (data/uploads).
3. Create a Run in 'pending' status for the worker to pick up.
"""
import os
import sys
import shutil
import uuid
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.getcwd())

from packages.db.database import get_session
from packages.db.models import Matter, Run, SourceDocument, Firm
from packages.shared.storage import save_upload

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def main():
    corpus_dir = Path("c:/CiteLine/New folder/ssa_corpus")
    if not corpus_dir.exists():
        print(f"Corpus directory not found: {corpus_dir}")
        return

    # Use a fixed firm/matter for the benchmark
    FIRM_NAME = "Benchmark Law Firm"
    MATTER_TITLE = "SSA Corpus Benchmark"

    with get_session() as session:
        # 1. Ensure Firm exists
        firm = session.query(Firm).filter_by(name=FIRM_NAME).first()
        if not firm:
            firm = Firm(name=FIRM_NAME)
            session.add(firm)
            session.flush()
            print(f"Created Firm: {firm.id}")

        # 2. Ensure Matter exists
        matter = session.query(Matter).filter_by(title=MATTER_TITLE, firm_id=firm.id).first()
        if not matter:
            matter = Matter(title=MATTER_TITLE, firm_id=firm.id)
            session.add(matter)
            session.flush()
            print(f"Created Matter: {matter.id}")

        # 3. Scan for PDFs
        pdf_files = list(corpus_dir.rglob("*.pdf"))
        print(f"Found {len(pdf_files)} PDFs in {corpus_dir}")

        for p in pdf_files:
            # Check if already imported (dedup by filename for now, strictly speaking should be hash)
            existing_doc = session.query(SourceDocument).filter_by(matter_id=matter.id, filename=p.name).first()
            if existing_doc:
                print(f"Skipping {p.name} (already imported)")
                continue

            file_bytes = p.read_bytes()
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            
            # Create SourceDocument
            doc_id = uuid.uuid4().hex
            save_upload(doc_id, file_bytes)
            
            doc = SourceDocument(
                id=doc_id,
                matter_id=matter.id,
                filename=p.name,
                mime_type="application/pdf",
                sha256=file_hash,
                bytes=len(file_bytes),
                uploaded_at=datetime.now(timezone.utc),
                page_count=0 # Will be filled by worker
            )
            session.add(doc)
            
            # Create Run
            run = Run(
                matter_id=matter.id,
                status="pending",
                config_json='{"max_pages": 500}' # Limit page count for benchmark speed
            )
            session.add(run)
            print(f"Queued {p.name} -> Run {run.id}")

        session.commit()
        print("Ingestion complete.")

if __name__ == "__main__":
    main()
