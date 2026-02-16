import json
from packages.db.database import get_db
from packages.db.models import Matter, Run

def queue_run():
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        matter = db.query(Matter).first()
        if not matter:
            print("No matter found!")
            return

        print(f"Found matter: {matter.id}")

        config = {
            "max_pages": 500,
            "include_billing_events_in_timeline": False,
            "pt_mode": "aggregate",
            "gap_threshold_days": 45,
            "event_confidence_min_export": 60,
            "low_confidence_event_behavior": "exclude_from_export",
        }

        run = Run(
            matter_id=matter.id,
            status="pending",
            config_json=json.dumps(config),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        print(f"Queued run: {run.id}")
        
    finally:
        db.close()

if __name__ == "__main__":
    queue_run()
