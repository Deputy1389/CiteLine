"""
Run CiteLine on generated MIMIC PDF packets.
"""
import os
import sys
import uuid
from pathlib import Path

# Add project root
root = Path(__file__).resolve().parent.parent
sys.path.append(str(root))
os.chdir(str(root))

from packages.db.database import get_session
from packages.db.models import Run, SourceDocument, Event
from packages.shared.models import RunStatus
from apps.worker.pipeline import run_pipeline

def main():
    pdf_path = Path("c:/CiteLine/data/mimic_demo/pdfs/Patient_100001.pdf")
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        return

    print(f"Ingesting {pdf_path}...")
    
    with get_session() as session:
        # Create Matter/SourceDoc
        # Simply reusing an existing matter or creating one for demo
        matter_id = "mimic_demo_matter"
        
        # Check if matter exists
        from packages.db.models import Matter
        matter = session.query(Matter).filter_by(id=matter_id).first()
        if not matter:
            matter = Matter(id=matter_id, title="MIMIC Demo Matter", firm_id="demo_firm")
            session.add(matter)
            session.commit()
            print(f"Created Matter {matter.id}")
        else:
            print(f"Found existing Matter {matter.id}")
            
        # Check if doc exists
        doc = session.query(SourceDocument).filter_by(filename=pdf_path.name).first()
        if not doc:
            doc = SourceDocument(
                id=str(uuid.uuid4()),
                matter_id=matter_id,
                filename=pdf_path.name,

                mime_type="application/pdf",
                storage_uri=str(pdf_path),
                sha256="a" * 64, # Valid length dummy
                bytes=pdf_path.stat().st_size
            )
            session.add(doc)
            session.commit()
            print(f"Created SourceDocument {doc.id}")
        if doc:
            print(f"Found existing SourceDocument {doc.id}")
            doc.sha256 = "a" * 64 # Ensure valid length
            session.flush()
            
        # Copy file to uploads dir so pipeline can find it
        from packages.shared.storage import get_upload_path
        import shutil
        dest = get_upload_path(doc.id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pdf_path, dest)
        print(f"Copied PDF to {dest}")
            
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
        print(f"Created Run {run_id}")
        
    # Run Pipeline
    print(f"Starting pipeline for Run {run_id}...")
    run_pipeline(run_id)
    
    # Check Results
    with get_session() as session:
        events = session.query(Event).filter_by(run_id=run_id).all()
        print("-" * 30)
        print(f"Extraction Complete. Found {len(events)} events.")
        for e in events:
            date_val = e.date_json.get("value") if e.date_json else "NO_DATE"
            summary = e.facts_json[0].get("text") if e.facts_json else "No facts"
            print(f"[{date_val}] {summary}")
            
if __name__ == "__main__":
    main()
