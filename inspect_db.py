
import sys
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add project root
sys.path.append("c:\\CiteLine")

from packages.db.database import get_db, DATABASE_URL
from packages.db.models import Run, Artifact

# The run_id from the logs
run_id = "f4e45ee736b34ca490ea58f597436d93"

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
    print("Artifacts:")
    artifacts = db.query(Artifact).filter_by(run_id=run_id).all()
    if not artifacts:
        print("  No artifacts found in DB")
    for a in artifacts:
        print(f"  - Type: {a.artifact_type}, Path: {a.storage_uri}")

db.close()
