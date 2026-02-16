import sys
import re
from datetime import date
from packages.shared.models.common import EventDate, DateKind, DateSource

# Mocking necessary parts since we can't easily import everything in isolation without setup
class MockPage:
    def __init__(self, text, page_number):
        self.text = text
        self.page_number = page_number
        self.source_document_id = "doc1"

# We need to import the actual module to test logic
from apps.worker.steps.events import clinical

def test_extraction():
    text = """
    9/24
    1600 Patient admitted to oncology floor.
    
    9/25 0800 Pt states pain is 8/10.
    
    Medication Administration Record
    This line should be skipped.
    
    10/01
    Discharge Summary due to stability.

    2016-10-10
    This date should generally be valid if explicit.

    1010 
    This is a time, not a date. Should NOT be 2016-10-10.

    Flowsheet
    General Appearance:
    Start of flowsheet block.

    09/24
    1900 Patient complained of pain 9/10, medicated.
    
    09/25 0830 Patient coughing.

    09/25
    2120 Patient vomited 275ml green emesis.

    09/26 0925 Orders received for discharge.
    """
    
    page = MockPage(text, 1)
    # Mock block object expected by _extract_block_events
    # The actual code iterates block.pages, so we need a mock block
    block = type("Block", (), {"pages": [page], "page_numbers": [1], "primary_date": None})()
    
    # Pass empty providers list
    events, _ = clinical._extract_block_events(block, {}, [])
    
    print(f"Extracted {len(events)} events.")
    for e in events:
        # Debug print
        print(f"Event: {e.date.extensions if e.date and e.date.extensions else 'NoDate'} Type: {e.event_type} Facts: {[f.text for f in e.facts]}")

    if len(events) < 6:
        print("FAILURE: Missing events. dumping all lines:")
        print(text)

    # Check for specific regression events
    facts_text = " ".join([f.text for e in events for f in e.facts])
    
    assert "pain 9/10" in facts_text, "Missing pain event"
    assert "vomited" in facts_text, "Missing emesis event"
    assert "Orders received" in facts_text, "Missing discharge orders"

    assert len(events) >= 6, f"Should extract at least 6 events, found {len(events)}"
    
    # Verify encounters
    types = [e.event_type for e in events]
    print(f"Types found: {types}")
    
    # Verify boilerplate skip
    boilerplate_texts = [f.text for e in events for f in e.facts if "Medication Administration Record" in f.text]
    assert not boilerplate_texts, "Boilerplate should be skipped"

    # BUG 2 CHECK: Flowsheet boilerplate
    flowsheet_texts = [f.text for e in events for f in e.facts if "General Appearance" in f.text or "Flowsheet" in f.text]
    assert not flowsheet_texts, "Flowsheet boilerplate should be skipped"
    
    # BUG 1 CHECK: Partial date invariant
    for e in events:
        if e.date and e.date.extensions and e.date.extensions.get("year_missing"):
            assert e.date.value is None, f"Partial date {e.date.extensions} has fabricated value {e.date.value}!"

    print("SUCCESS: Extraction verified.")

def test_split_block_context():
    """Test extraction when block has date but text does not (split block scenario)."""
    print("\nRunning Split Block Test...")
    # Mock date object (Partial Date 9/24)
    mock_date = type("EventDate", (), {
        "value": None,
        "extensions": {"partial_date": True, "partial_month": 9, "partial_day": 24}
    })()
    
    text = "1900 Patient admitted via ER."
    page = MockPage(text, 2)
    block = type("Block", (), {
        "pages": [page], 
        "page_numbers": [2], 
        "primary_date": mock_date
    })()
    
    events, _ = clinical._extract_block_events(block, {}, [])
    
    if not events:
        print("FAILURE: No events extracted from split block.")
        exit(1)
        
    e = events[0]
    # Check date was inherited
    assert e.date.extensions["partial_month"] == 9
    assert e.date.extensions["partial_day"] == 24
    assert "Patient admitted" in e.facts[0].text
    print("SUCCESS: Split block extraction verified.")

if __name__ == "__main__":
    test_extraction()
    test_split_block_context()
