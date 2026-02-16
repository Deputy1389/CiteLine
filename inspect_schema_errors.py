from packages.db.database import get_session
from packages.db.models import Run
import json

def inspect_latest_run():
    with get_session() as session:
        latest_run = session.query(Run).order_by(Run.created_at.desc()).first()
        if not latest_run:
            print("No runs found.")
            return
        
        print(f"Run ID: {latest_run.id}")
        print(f"Status: {latest_run.status}")
        print(f"Error Message: {latest_run.error_message}")
        
        if latest_run.warnings_json:
            warnings = json.loads(latest_run.warnings_json)
            schema_errors = [w for w in warnings if w.get("code") == "SCHEMA_VALIDATION_ERROR"]
            print(f"\nSchema Errors ({len(schema_errors)}):")
            for i, err in enumerate(schema_errors[:20]):
                print(f"  [{i}] {err.get('message')}")
        else:
            print("\nNo warnings found.")

if __name__ == "__main__":
    inspect_latest_run()
