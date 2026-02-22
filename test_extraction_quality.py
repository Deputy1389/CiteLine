"""
Test extraction quality with OCR enabled.
This script:
1. Creates a test matter
2. Uploads a document from the uploads folder
3. Queues a run with OCR enabled
4. Monitors run progress
"""
import sys
import os
import time
import json
from pathlib import Path

sys.path.insert(0, "C:/Citeline")

# Explicitly disable OCR flag for this test
os.environ["DISABLE_OCR"] = "false"
os.environ["OCR_MODE"] = "full"

from packages.db.database import get_db
from packages.db.models import Matter, Run, SourceDocument, Firm
from packages.shared.storage import save_upload, sha256_bytes

def main():
    db = next(get_db())

    try:
        # 1. Get or create a firm
        firm = db.query(Firm).first()
        if not firm:
            firm = Firm(name="Test Firm")
            db.add(firm)
            db.commit()
            db.refresh(firm)
        print(f"Using firm: {firm.name} ({firm.id})")

        # 2. Create a new matter
        matter = Matter(
            firm_id=firm.id,
            title="OCR Quality Test - Large Packet",
            client_ref="TEST-OCR-001",
        )
        db.add(matter)
        db.commit()
        db.refresh(matter)
        print(f"Created matter: {matter.title} ({matter.id})")

        # 3. Find a large PDF in the uploads directory to use as test data
        uploads_dir = Path("C:/Citeline/data/uploads")
        test_pdf = None
        largest_size = 0

        for pdf_file in uploads_dir.glob("*.pdf"):
            size = pdf_file.stat().st_size
            if size > largest_size:
                largest_size = size
                test_pdf = pdf_file

        if not test_pdf:
            print("No PDF files found in uploads directory!")
            return

        print(f"Using test PDF: {test_pdf.name} ({largest_size:,} bytes)")

        # 4. Create source document record
        file_content = test_pdf.read_bytes()
        file_hash = sha256_bytes(file_content)

        doc = SourceDocument(
            matter_id=matter.id,
            filename=test_pdf.name,
            mime_type="application/pdf",
            sha256=file_hash,
            bytes=len(file_content),
        )
        db.add(doc)
        db.flush()

        # Save to storage
        saved_path = save_upload(doc.id, file_content)
        doc.storage_uri = str(saved_path)
        db.commit()
        db.refresh(doc)
        print(f"Created document: {doc.filename} ({doc.id})")

        # 5. Queue a run with full OCR enabled
        config = {
            "max_pages": 500,
            "include_billing_events_in_timeline": True,
            "pt_mode": "aggregate",
            "gap_threshold_days": 45,
            "event_confidence_min_export": 60,
            "low_confidence_event_behavior": "include_in_export",
            # OCR settings
            "ocr_enabled": True,  # Explicitly enable
        }

        run = Run(
            matter_id=matter.id,
            status="pending",
            config_json=json.dumps(config),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        print(f"\n{'='*60}")
        print(f"QUEUED RUN: {run.id}")
        print(f"{'='*60}")
        print(f"Matter: {matter.title}")
        print(f"Document: {doc.filename}")
        print(f"OCR Mode: full (DISABLE_OCR=false)")
        print(f"Max Pages: {config['max_pages']}")
        print(f"\nRun status: {run.status}")
        print(f"\nTo monitor this run:")
        print(f"  - Check http://localhost:3000/app/cases (if UI is running)")
        print(f"  - Or query database: SELECT status FROM runs WHERE id='{run.id}'")
        print(f"\nNext steps:")
        print(f"  1. Start the worker: python -m apps.worker.runner")
        print(f"  2. Monitor run status (should transition: pending -> running -> success/failed)")
        print(f"  3. Check for 'UNDATED' events and word salad in the output")
        print(f"  4. Verify Evidence Vault loads documents")
        print(f"  5. Check that Strategic Overview shows moat features")
        print(f"\n{'='*60}\n")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()
