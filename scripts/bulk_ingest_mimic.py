"""
Bulk Ingest and Stress Test for MIMIC-IV Synthetic Corpus.
Processes 50+ large patient PDFs and measures extraction performance.
"""
import os
import sys
import uuid
import time
import shutil
from pathlib import Path

# Add project root
root = Path(__file__).resolve().parent.parent
sys.path.append(str(root))
os.chdir(str(root))

from packages.db.database import get_session
from packages.db.models import Run, SourceDocument, Event, Matter
from packages.shared.models import RunStatus
from packages.shared.storage import get_upload_path
from apps.worker.pipeline import run_pipeline

def main():
    pdf_dir = Path("c:/CiteLine/data/mimic_demo/real_packets")
    pdf_files = list(pdf_dir.glob("Patient_*.pdf"))
    
    if not pdf_files:
        print(f"No PDFs found in {pdf_dir}")
        return

    print(f"Found {len(pdf_files)} PDFs for bulk stress test.")
    
    total_start = time.time()
    results = []
    
    with get_session() as session:
        # Ensure Matter exists
        matter_id = "mimic_bulk_stress_test"
        matter = session.query(Matter).filter_by(id=matter_id).first()
        if not matter:
            matter = Matter(id=matter_id, title="MIMIC Bulk Stress Test", firm_id="demo_firm")
            session.add(matter)
            session.commit()

    for i, pdf_path in enumerate(pdf_files):
        print(f"[{i+1}/{len(pdf_files)}] Processing {pdf_path.name}...")
        start_time = time.time()
        
        with get_session() as session:
            # SourceDoc
            doc = session.query(SourceDocument).filter_by(filename=pdf_path.name, matter_id=matter_id).first()
            if not doc:
                doc = SourceDocument(
                    id=str(uuid.uuid4()),
                    matter_id=matter_id,
                    filename=pdf_path.name,
                    mime_type="application/pdf",
                    storage_uri=str(pdf_path),
                    sha256="a" * 64,
                    bytes=pdf_path.stat().st_size
                )
                session.add(doc)
            else:
                doc.sha256 = "a" * 64
                
            session.flush()
            doc_id = doc.id
            
            # Copy to uploads
            dest = get_upload_path(doc_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(pdf_path, dest)
            
            # Create Run
            run = Run(
                id=str(uuid.uuid4()).replace('-', ''),
                matter_id=matter_id,
                status=RunStatus.PENDING,
                config_json={}
            )
            run_id = run.id
            session.add(run)
            session.commit()
            
        # Run Pipeline
        try:
            run_pipeline(run_id)
        except Exception as e:
            print(f"Error processing {pdf_path.name}: {e}")
            continue
            
        # Record Metric
        duration = time.time() - start_time
        with get_session() as session:
            event_count = session.query(Event).filter_by(run_id=run_id).count()
        
        results.append({
            "name": pdf_path.name,
            "duration": duration,
            "events": event_count
        })
        print(f"  Completed in {duration:.2f}s | Events: {event_count}")

    total_duration = time.time() - total_start
    total_events = sum(r['events'] for r in results)
    
    print("\n" + "="*40)
    print("MIMIC BULK STRESS TEST RESULTS")
    print("="*40)
    print(f"Total Documents: {len(pdf_files)}")
    print(f"Total Admissions: ~{total_events}") # Roughly 1:1 with admissions in this generator
    print(f"Total Time:      {total_duration:.2f}s")
    print(f"Average Time:    {total_duration/len(pdf_files):.2f}s per doc")
    print(f"Throughput:      {len(pdf_files)/(total_duration/60):.2f} docs/min")
    print("="*40)

if __name__ == "__main__":
    main()
