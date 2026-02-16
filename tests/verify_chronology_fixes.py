import sys
import os
from datetime import date

# Mock imports for standalone test
class MockPage:
    def __init__(self, text, page_number=1, source_document_id="doc1"):
        self.text = text
        self.page_number = page_number
        self.source_document_id = source_document_id

# 1. Test Demographics
from apps.worker.steps.step03a_demographics import extract_demographics

def test_demographics():
    print("Testing Demographics Extraction...")
    pages = [
        MockPage("Patient is a 65-year-old female presenting with cough."),
        MockPage("Sex: F, Age: 66")
    ]
    patient, _ = extract_demographics(pages)
    print(f"Resolved Sex: {patient.sex}, Age: {patient.age}, Confidence: {patient.sex_confidence}")
    assert patient.sex == "female"
    assert patient.age == 65 or patient.age == 66
    print("✓ Demographics passed!")

# 2. Test Encounter Classification
from apps.worker.steps.events.clinical import _detect_encounter_type
from packages.shared.models import EventType

def test_encounter_classification():
    print("\nTesting Encounter Classification...")
    ed_text = "Patient arrived in the emergency department triage."
    ip_text = "Nursing Flowsheet: Patient stable on Oncology Floor."
    ov_text = "Chief Complaint: Follow up visit."
    
    assert _detect_encounter_type(ed_text) == EventType.ER_VISIT
    assert _detect_encounter_type(ip_text) == EventType.INPATIENT_DAILY_NOTE
    assert _detect_encounter_type(ov_text) == EventType.OFFICE_VISIT
    print("✓ Encounter classification passed!")

# 3. Test Date Resolution (Year Filtering)
from apps.worker.steps.step06_dates import _parse_date_from_match
import re

def test_date_filtering():
    print("\nTesting Date Year Filtering...")
    # Pattern 0 is MM/DD/YYYY
    pattern = r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})"
    
    m1 = re.search(pattern, "09/24/2016")
    d1 = _parse_date_from_match(m1, 0)
    print(f"Valid date: {d1}")
    assert d1 == date(2016, 9, 24)
    
    m2 = re.search(pattern, "01/01/1897")
    d2 = _parse_date_from_match(m2, 0)
    print(f"Invalid date (1897): {d2}")
    assert d2 is None
    print("✓ Date filtering passed!")

if __name__ == "__main__":
    # Add project root to sys.path
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        
    try:
        test_demographics()
        test_encounter_classification()
        test_date_filtering()
        print("\nALL TESTS PASSED!")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
