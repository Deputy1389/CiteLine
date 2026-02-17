from packages.db.database import get_db
from packages.db.models import Event, Run
import json

def verify_run(run_id: str):
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        print(f"Run ID: {run_id}")
        print(f"Status: {run.status}")
        
        events = db.query(Event).filter(Event.run_id == run_id).all()
        print(f"Total Events: {len(events)}")
        
        # Sort using sort_key equivalent logic for dicts
        def sort_key(e):
            dj = e.date_json or {}
            ext = dj.get("extensions") or {}
            m = dj.get("partial_month") or 0
            d = dj.get("partial_day") or 0
            time = ext.get("time", "0000")
            return (m, d, time)
            
        sorted_evts = sorted(events, key=sort_key)
        
        print("\nSPECIFIC 09/26 EVENTS:")
        found_0926 = False
        for e in sorted_evts:
            dj = e.date_json or {}
            if dj.get("partial_month") == 9 and dj.get("partial_day") == 26:
                found_0926 = True
                ext = dj.get("extensions") or {}
                time = ext.get("time", "0000")
                facts = "; ".join([f.get("text") for f in (e.facts_json or [])])
                print(f"[{time}] {e.event_type}: {facts[:150]}...")
        
        if not found_0926:
            print("❌ No 09/26 events found!")

    finally:
        db.close()

if __name__ == "__main__":
    verify_run("f0a29d4d38d4465f918e3d301f9a5206")
