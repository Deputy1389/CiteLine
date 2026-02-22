"""Check for test45 matter and its runs."""
import sys
sys.path.insert(0, "C:/Citeline")

from packages.db.database import get_db
from packages.db.models import Matter, Run, SourceDocument

db = next(get_db())

try:
    # Look for test45 or packet.pdf
    matters = db.query(Matter).all()
    print(f"\nTotal matters: {len(matters)}")

    for m in matters[:10]:  # Show first 10
        docs = db.query(SourceDocument).filter_by(matter_id=m.id).all()
        runs = db.query(Run).filter_by(matter_id=m.id).all()
        print(f"\nMatter: {m.title or m.id[:8]}")
        print(f"  Documents: {len(docs)}")
        for d in docs[:3]:
            print(f"    - {d.filename} ({d.bytes} bytes)")
        print(f"  Runs: {len(runs)}")
        for r in runs[:3]:
            print(f"    - {r.id[:8]}: {r.status}")

    # Look specifically for packet.pdf or test45
    packet_doc = db.query(SourceDocument).filter(
        SourceDocument.filename.like("%packet%")
    ).first()

    if packet_doc:
        print(f"\nFound packet.pdf: {packet_doc.id}")
        matter = db.query(Matter).filter_by(id=packet_doc.matter_id).first()
        if matter:
            print(f"  Matter: {matter.title or matter.id}")

finally:
    db.close()
