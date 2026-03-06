import re
from packages.shared.models import EventType

# Priority map for upgrading encounter types during assembly
PRIORITY_MAP = {
    EventType.ER_VISIT: 6,
    EventType.HOSPITAL_ADMISSION: 5,
    EventType.HOSPITAL_DISCHARGE: 5,
    EventType.PROCEDURE: 4,
    EventType.OFFICE_VISIT: 3,
    EventType.INPATIENT_DAILY_NOTE: 2,
}

def detect_encounter_type(text: str) -> EventType:
    """Detect encounter type from clinical note text with deterministic rules."""
    n = text.lower()

    # 0a. Intake forms
    _INTAKE_MARKERS = (
        "intake questionnaire", "patient intake", "new patient intake", "intake form",
        "registration form", "patient registration", "medical history form",
        "assignment of benefits", "authorization for treatment"
    )
    if any(m in n for m in _INTAKE_MARKERS):
        return EventType.OFFICE_VISIT

    # 0b. Historical Reference Detection
    if re.search(r"\b(discharged home on|admitted on|prior to|reported on|history of)\s+\d{1,2}/\d{1,2}\b", n):
        return EventType.REFERENCED_PRIOR_EVENT
    if "history of" in n and len(n) < 100:
        return EventType.REFERENCED_PRIOR_EVENT

    # 1. Discharge
    discharge_patterns = [
        "discharge summary", "discharged", "discharge teaching", "discharge instructions",
        "orders received for discharge", "discharged to home", "discharge order",
        "patient discharged", "discharge disposition", "discharge plan",
        "discharge medications", "discharged from hospital", "discharge condition",
        "discharge to", "upon discharge", "at time of discharge"
    ]
    if any(kw in n for kw in discharge_patterns):
        return EventType.HOSPITAL_DISCHARGE

    # 1.5 Explicit ED/ER visit cues
    er_anchors = [
        "seen in er", "seen in ed", "er visit", "ed visit", "emergency room",
        "emergency department", "emergency visit", "er evaluation", "ed evaluation",
        "arrived to er", "arrived to ed", "brought to er", "brought to ed", "triage note"
    ]
    er_process = ["triage level", "triage category", "emergency physician", "er intake", "ed intake"]
    
    if any(kw in n for kw in er_anchors):
        if any(kw in n for kw in ["prior", "history of", "previous"]):
             return EventType.OFFICE_VISIT
        return EventType.ER_VISIT
    
    if any(kw in n for kw in er_process):
        if any(kw in n for kw in ["emergency", "room 4", "ambulance", "ems", "trauma", "interim lsu"]):
            return EventType.ER_VISIT

    # 2. Admission
    admission_patterns = [
        "admitted", "admission", "admit to oncology",
        "inpatient admission", "admit to oncology floor", "hospital admission",
        "admitted to hospital", "admitted for", "direct admission", "admit orders",
        "admit date", "inpatient"
    ]
    if any(kw in n for kw in admission_patterns):
        if not re.search(r"date\s+admitted\s*:", n):
            return EventType.HOSPITAL_ADMISSION

    # 3. Procedure
    procedure_patterns = [
        "operative report", "procedure", "surgery", "surgical", "operation",
        "pre-op", "post-op", "intraoperative", "anesthesia", "incision",
        "excision", "biopsy", "resection"
    ]
    if any(kw in n for kw in procedure_patterns):
        return EventType.PROCEDURE

    # 4. PT / Physical Therapy
    pt_patterns = [
        "physical therapy", "pt eval", "pt note", "pt assessment", "therapist",
        "ambulation", "gait", "balance", "mobility", "range of motion", "rom",
        "therapeutic exercise", "transfer", "walker", "cane", "assistive device",
        "functional status", "manual therapy", "home exercise program"
    ]
    if any(kw in n for kw in pt_patterns):
        return EventType.OFFICE_VISIT

    # 5. Office Visit
    office_patterns = [
        "office visit", "clinic visit", "outpatient", "follow-up", "follow up",
        "consultation", "consult", "evaluation", "treatment plan discussion",
        "modified duty", "work status", "return to work", "specialist follow-up",
        "orthopedic", "orthopaedic", "pain management", "neurosurgery", "physiatry"
    ]
    if any(kw in n for kw in office_patterns):
        return EventType.OFFICE_VISIT

    # Default for inpatient records
    return EventType.INPATIENT_DAILY_NOTE
