import json
import uuid
import os
from datetime import datetime, timezone
from packages.db.database import get_session, init_db
from packages.db.models import Matter, Run, SourceDocument, Firm
from apps.worker.pipeline import run_pipeline
from pathlib import Path

def setup_and_run():
    init_db()
    with get_session() as session:
        # 1. Setup Firm/Matter
        firm = Firm(name="Debug Firm")
        session.add(firm)
        session.flush()
        
        matter = Matter(firm_id=firm.id, title="Julia Morales Debug")
        session.add(matter)
        session.flush()
        
        # 2. Add Documents
        testdata = Path("C:/CiteLine/testdata")
        julia_files = [
            "eval_06_julia_day1.pdf",
            "eval_07_julia_day2.pdf",
            "eval_08_julia_day3.pdf"
        ]
        
        for fname in julia_files:
            fpath = testdata / fname
            if not fpath.exists():
                print(f"Missing {fname}")
                continue
                
            doc = SourceDocument(
                matter_id=matter.id,
                filename=fname,
                mime_type="application/pdf",
                sha256="0"*64, # Mock
                bytes=fpath.stat().st_size
            )
            session.add(doc)
            session.flush()
            
            # Link file in data/uploads/
            upload_dir = Path("C:/CiteLine/data/uploads")
            upload_dir.mkdir(parents=True, exist_ok=True)
            target = upload_dir / f"{doc.id}.pdf"
            # Copy or symlink
            import shutil
            shutil.copy(fpath, target)

        # 3. Create Run
        config = {
            "max_pages": 100,
            "low_confidence_event_behavior": "include_with_flag",
            "event_confidence_min_export": 50
        }
        run = Run(
            matter_id=matter.id,
            status="pending",
            config_json=json.dumps(config)
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()
        
    print(f"🚀 Starting pipeline for run {run_id}")
    run_pipeline(run_id)
    
    # 4. Check results
    from inspect_schema_errors import inspect_latest_run
    inspect_latest_run()

if __name__ == "__main__":
    setup_and_run()
