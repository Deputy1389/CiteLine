
import sys
import os
import json
from pathlib import Path

# Add project root
sys.path.append(os.getcwd())

from apps.worker.steps.step01_page_split import split_pages
from apps.worker.steps.step03b_patient_partitions import build_patient_partitions
from packages.shared.models import SourceDocument

def test_partitioning(pdf_path: str):
    print("Running V2 with Confidence Fix - UPDATED")
    print(f"Testing partitioning on {pdf_path}")
    source_pdf = Path(pdf_path)
    if not source_pdf.exists():
        print("File not found.")
        return

    # 1. Mock Source Document
    with open(source_pdf, "rb") as f:
        pdf_bytes = f.read()
    
    try:
        pages, warnings = split_pages(str(source_pdf), "dummy_doc_id")
        print(f"Split into {len(pages)} pages.")
        
        # 2. Run Partitioning
        payload, page_scope_map = build_patient_partitions(pages)
        print(json.dumps(payload, indent=2))

        # 3. Simulate Event Filtering logic from chronology.py
        import apps.worker.project.chronology as chronology_module
        from apps.worker.project.chronology import _is_high_value_event, _is_vitals_heavy
        from packages.shared.models import Event, EventType, Fact, EventDate
        from packages.shared.models.enums import DateKind, DateSource, FactKind
        from datetime import date
        
        print(f"DEBUG: chronology module loaded from: {chronology_module.__file__}")
        print(f"DEBUG: EventType.INPATIENT_DAILY_NOTE value: '{EventType.INPATIENT_DAILY_NOTE.value}'")
        
        print("\n--- Testing Filtering Logic ---")
        
        # Create mock events based on ExtractionNotes
        mock_events = [
            Event(
                event_id="e1",
                event_type=EventType.INPATIENT_DAILY_NOTE,
                date=EventDate(
                    value=date(2005, 11, 21), 
                    original_text="2005-11-21",
                    kind=DateKind.SINGLE,
                    source=DateSource.TIER1
                ),
                facts=[Fact(
                    text="Acetaminophen 325 MG Oral Tablet",
                    kind=FactKind.MEDICATION,
                    verbatim=True
                )],
                provider_id="p1",
                confidence=95.0
            ),
             Event(
                event_id="e2", # Vitals heavy
                event_type=EventType.INPATIENT_DAILY_NOTE,
                date=EventDate(
                    value=date(2016, 2, 25), 
                    original_text="2016-02-25",
                    kind=DateKind.SINGLE,
                    source=DateSource.TIER1
                ),
                facts=[
                    Fact(text="Body Height: 162.8 cm", kind=FactKind.FINDING, verbatim=True),
                    Fact(text="Body Weight: 73.8 kg", kind=FactKind.FINDING, verbatim=True), 
                    Fact(text="Pain severity - 0-10", kind=FactKind.FINDING, verbatim=True),
                    Fact(text="Acetaminophen 325 MG", kind=FactKind.MEDICATION, verbatim=True),
                ],
                provider_id="p1",
                confidence=95.0
            ),
             Event(
                event_id="e3", # Lab result (might be low value if not high priority type)
                event_type=EventType.LAB_RESULT,
                date=EventDate(
                    value=date(2005, 11, 21), 
                    original_text="2005-11-21",
                    kind=DateKind.SINGLE,
                    source=DateSource.TIER1
                ),
                facts=[Fact(
                    text="Labs found: Hemoglobin, Hematocrit",
                    kind=FactKind.LAB,
                    verbatim=True
                )],
                provider_id="p1",
                confidence=95.0
            )
        ]

        for e in mock_events:
            joined_raw = " ".join(f.text for f in e.facts)
            is_high = _is_high_value_event(e, joined_raw)
            print(f"Event {e.event_id} ({e.event_type.value}): HighValue={is_high}")
            
            clean_facts = []
            for f in e.facts:
                if _is_vitals_heavy(f.text):
                    print(f"  Dropped Fact (Vitals): {f.text}")
                    continue
                clean_facts.append(f.text)
            
            if not is_high or not clean_facts:
                 print(f"  -> DROPPED from Projection (HighValue={is_high}, Facts={len(clean_facts)})")
            else:
                 print(f"  -> KEPT")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    pdf = r"c:\CiteLine\New folder\run_3d1274b664904355a9c75e74c4a8d67b_pdf.pdf"
    test_partitioning(pdf)
