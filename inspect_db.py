
import sys
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add project root
sys.path.append("c:\\CiteLine")

from packages.db.database import get_db, DATABASE_URL
from packages.db.models import Run, Artifact

# The run_id from the logs
run_id = sys.argv[1] if len(sys.argv) > 1 else "ed7f67ce1e6345c29189875e4a6e24b2"

# Connect to DB
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

print(f"Checking Run: {run_id}")
run = db.query(Run).filter_by(id=run_id).first()
if not run:
    print("Run NOT FOUND")
else:
    print(f"Run found. Status: {run.status}")
    if run.error_message:
        print(f"Error: {run.error_message}")
    if run.warnings_json:
        import json
        warns = json.loads(run.warnings_json)
        print(f"Warnings ({len(warns)}):")
        for w in warns[:10]:
            print(f"  - {w.get('code')}: {w.get('message')[:100]}")
        
        schema_errs = [w for w in warns if w.get('code') == 'SCHEMA_VALIDATION_ERROR']
        if schema_errs:
            print(f"Found {len(schema_errs)} SCHEMA_VALIDATION_ERRORs:")
            for w in schema_errs[:5]:
                print(f"  !! {w.get('message')}")
    
    print("Artifacts:")
    artifacts = db.query(Artifact).filter_by(run_id=run_id).all()
    if not artifacts:
        print("  No artifacts found in DB")
    for a in artifacts:
        print(f"  - Type: {a.artifact_type}, Path: {a.storage_uri}")

db.close()
