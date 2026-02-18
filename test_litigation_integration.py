
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Mock project root
sys.path.append(os.getcwd())

from packages.shared.models import Event, EventType

from apps.worker.steps.step12b_litigation_review import run_litigation_review

def test_integration():
    print("Testing Litigation Review Step Integration...")
    
    # 1. Setup Mock Data
    run_id = "test_integration_run"
    
    # Create some dummy events
    e1 = Event(
        event_id="e1",
        date={"value": "2023-01-01", "resolution": "day", "source": "tier1", "kind": "single"}, 
        event_type=EventType.INPATIENT_DAILY_NOTE,
        facts=[{"text": "Patient complained of pain.", "kind": "finding", "verbatim": True}],
        citation_ids=["f1_p1"],
        confidence=90,
        extensions={"citations": [{"source_file_id": "f1", "page_number": 1}]}
    )
    
    e2 = Event(
        event_id="e2",
        date={"value": "2023-01-02", "resolution": "day", "source": "tier1", "kind": "single"},
        event_type=EventType.LAB_RESULT,
        facts=[{"text": "Lab result normal.", "kind": "finding", "verbatim": True}],
        citation_ids=[], # Missing citation to trigger H4
        confidence=90,
        extensions={}
    )
    
    # Needs to be a list of Event objects
    events = [e1, e2]
    
    # Page text
    page_text = {1: "Page 1 text with no issues.", 2: "Page 2 text."}
    
    # 2. Run Step
    try:
        checklist, warnings = run_litigation_review(run_id, events, page_text)
    except Exception as e:
        print(f"FAILED: Step execution crashed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. Verify Outputs
    print(f"Result Score: {checklist['score_0_100']}")
    print(f"Pass: {checklist['pass']}")
    print(f"Warnings: {len(warnings)}")
    
    # Check artifacts
    if os.path.exists(f"artifacts/{run_id}/qa_litigation_checklist.json"):
        print("Artifact CHECK: qa_litigation_checklist.json created.")
    else:
        print("Artifact FAIL: qa_litigation_checklist.json missing.")

    if os.path.exists(f"artifacts/{run_id}/litigation_review.md"):
        print("Artifact CHECK: litigation_review.md created.")
    else:
        print("Artifact FAIL: litigation_review.md missing.")

    # 4. Verify Logic
    # H4 check (citations)
    h4_res = checklist['hard_invariants'].get('H4', {})
    if not h4_res.get('pass'):
        print("Logic CHECK: H4 failed correctly.")
    else:
        print(f"Logic FAIL: H4 passed unexpectedly. Details: {h4_res}")
    
    # H6 check (Contamination) - Pass e3 with 'run_' provider
    # Not testing here to keep simple, just verifying H4 and general artifacts.

    # Cleanup (optional)
    # import shutil
    # shutil.rmtree(f"artifacts/{run_id}")

if __name__ == "__main__":
    # Ensure artifact dir exists for mock
    os.makedirs(f"artifacts/test_integration_run", exist_ok=True)
    
    # Mock save_artifact to write to local dir
    import packages.shared.storage
    def mock_save_artifact(run_id, filename, data):
        path = Path(f"artifacts/{run_id}/{filename}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
        return path
    
    packages.shared.storage.save_artifact = mock_save_artifact
    
    test_integration()
