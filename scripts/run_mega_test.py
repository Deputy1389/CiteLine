"""
Extreme Scaling Test: Processes the 1000-page Mega-Packet.
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
    pdf_path = Path("c:/CiteLine/data/synthea/packets/MEGA_STRESS_TEST_1000_PAGES.pdf")
    
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        return

    print(f"Initiating Extreme Scaling Test on {pdf_path.name} ({pdf_path.stat().st_size / 1024 / 1024:.2f} MB)")
    
    matter_id = "extreme_scaling_test"
    with get_session() as session:
        matter = session.query(Matter).filter_by(id=matter_id).first()
        if not matter:
            matter = Matter(id=matter_id, title="Extreme Scaling Stress Test", firm_id="demo_firm")
            session.add(matter)
            session.commit()

    start_time = time.time()
    
    with get_session() as session:
        doc = SourceDocument(
            id=str(uuid.uuid4()),
            matter_id=matter_id,
            filename=pdf_path.name,
            mime_type="application/pdf",
            storage_uri=str(pdf_path),
            sha256="c" * 64, 
            bytes=pdf_path.stat().st_size
        )
        session.add(doc)
        session.flush()
        doc_id = doc.id
        
        dest = get_upload_path(doc_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pdf_path, dest)
        
        run = Run(
            id=str(uuid.uuid4()).replace('-', ''),
            matter_id=matter_id,
            status=RunStatus.PENDING,
            config_json={}
        )
        run_id = run.id
        session.add(run)
        session.commit()
        
    print(f"Running pipeline for Run {run_id} (Target: 1000+ pages)...")
    try:
        run_pipeline(run_id)
        duration = time.time() - start_time
        with get_session() as session:
            event_count = session.query(Event).filter_by(run_id=run_id).count()
        
        print("\n" + "="*40)
        print("EXTREME SCALING TEST COMPLETED")
        print("="*40)
        print(f"File:           {pdf_path.name}")
        print(f"Pages (est):    1100")
        print(f"Events Extracted: {event_count}")
        print(f"Total Time:      {duration:.2f}s")
        print(f"Average Rate:    {duration/1100:.4f}s per page")
        print("="*40)
        
    except Exception as e:
        print(f"FAILED Extreme Scaling Test: {e}")

if __name__ == "__main__":
    main()
