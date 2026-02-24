import re
import logging
from packages.shared.models import Event, EventType

logger = logging.getLogger(__name__)

BOILERPLATE_PATTERNS = [
    r"(?i)^date:?$",
    r"(?i)^date/time:?$",
    r"(?i)^date of",
    r"(?i)^vital signs record$",
    r"(?i)^prn medications$",
    r"(?i)^scheduled & routine drugs$",
    r"(?i)^allergies:?$",
    r"(?i)^patient name:?$",
    r"(?i)^doctor name:?$",
    r"(?i)^mrn:?$",
    r"(?i)^chart materials",
    r"^©",
    r"(?i)^national league",
    r"^[_\s]+$",  # Lines containing only underscores or blanks
    r".*_{3,}.*",  # Lines with multiple underscores (placeholders)
]

LEGEND_PATTERNS = [
    r"(?i)^[e-f]=[r|l]\s+thigh",
    r"(?i)^[c-d]=[r|l]\s+deltoid",
]

CLINICAL_VERBS = [
    # Active voice clinical actions
    "complained", "denies", "vomited", "ambulated", "assisted",
    "administered", "medicated", "discharged", "admitted",
    "coughing", "repositioned", "ate", "requested", "vomit", "emesis", "nausea",

    # Passive voice medical documentation (common in radiology/diagnostics)
    "noted", "identified", "revealed", "demonstrated", "confirmed",
    "diagnosed", "observed", "indicated", "showing", "consistent with",
    "obtained", "reviewed", "correlated", "assessed", "evaluated",

    # Medical findings/observations
    "reveals", "shows", "suggests", "supports", "evidenced",
    "documented", "recorded", "reported", "found", "detected",

    # Clinical examination verbs
    "examined", "palpated", "inspected", "auscultated", "percussed",

    # Treatment/procedure verbs
    "treated", "prescribed", "performed", "injected", "applied",
    "ordered", "recommended", "continued", "adjusted", "modified"
]

NUMERIC_SIGNALS = [
    r"\d{1,2}/10",  # Pain score (X/10)
    r"\d{2,3}\s*lbs?",  # Weight values
    r"\d{1,4}\s*(?:mg|ml|g|mcg|unit)",  # Medication dose
    r"(?i)\b(?:bp|temp|hr|rr|o2|sat)\b",  # Vital signs labels
    r"(?i)\b(?:t1|t2)\s*weighted",  # MRI sequences
    r"(?i)\b(?:ap|lateral|axial|sagittal|coronal)\b",  # Imaging views
    r"(?i)\b(?:c\d-?\d|l\d-?\d|t\d-?\d)\b",  # Spinal levels (C5-C6, L4-L5, etc.)
    r"(?i)\bmm\b",  # Millimeters (medical measurements)
    r"(?i)\bcm\b",  # Centimeters (medical measurements)
]

# Medical diagnosis/condition terminology that indicates clinical significance
MEDICAL_DIAGNOSIS_TERMS = [
    r"(?i)\b(?:fracture|herniation|stenosis|spondylosis|arthritis|effusion)\b",
    r"(?i)\b(?:strain|sprain|contusion|laceration|abrasion|hematoma)\b",
    r"(?i)\b(?:edema|swelling|inflammation|infection|abscess)\b",
    r"(?i)\b(?:radiculopathy|neuropathy|myelopathy|sciatica)\b",
    r"(?i)\b(?:degeneration|degenerative|bulging|protrusion|extrusion)\b",
    r"(?i)\b(?:tear|rupture|lesion|mass|nodule|cyst)\b",
    r"(?i)\b(?:hemorrhage|bleed|ischemia|infarct)\b",
    r"(?i)\b(?:hypertension|diabetes|copd|asthma)\b",
    r"(?i)\b(?:chronic|acute|subacute|severe|moderate|mild)\b",
    r"(?i)\b(?:impression|findings|diagnosis|assessment)\b",
]

def is_clinical_signal_event(event: Event) -> bool:
    """
    Returns True if the event contains meaningful clinical signal.
    Drops events that are only scaffolding, legends, or template text.
    """
    if not event.facts:
        return False

    # Admission, Discharge, and specialist event types always pass if they have facts.
    # Specialist extractors (imaging, PT, lab, billing) only run on their dedicated page types,
    # so if they produced facts they are inherently meaningful clinical content.
    _ALWAYS_PASS = {
        EventType.HOSPITAL_ADMISSION,
        EventType.HOSPITAL_DISCHARGE,
        EventType.PT_VISIT,
        EventType.IMAGING_STUDY,
        EventType.LAB_RESULT,
        EventType.BILLING_EVENT,
        EventType.PROCEDURE,
    }
    if event.event_type in _ALWAYS_PASS:
        return True

    has_signal = False
    non_boilerplate_count = 0
    
    for fact in event.facts:
        text = fact.text.strip()
        text_lower = text.lower()
        
        # Check boilerplate
        is_boilerplate = any(re.search(p, text) for p in BOILERPLATE_PATTERNS)
        is_legend = any(re.search(p, text) for p in LEGEND_PATTERNS)
        
        if is_boilerplate or is_legend:
            continue
            
        non_boilerplate_count += 1
            
        # Requirement: Check for Clinical Verbs
        has_verb = any(verb in text_lower for verb in CLINICAL_VERBS)

        # Requirement: Check for Numeric Signal
        has_numeric = any(re.search(p, text_lower) for p in NUMERIC_SIGNALS)

        # Requirement: Check for Medical Diagnosis Terms
        has_medical_term = any(re.search(p, text_lower) for p in MEDICAL_DIAGNOSIS_TERMS)

        # Requirement: Length rule
        # lines shorter than 15 characters UNLESS they contain numeric clinical value
        is_long_enough = len(text) >= 15

        # Pass if:
        # 1. Has clinical verb + reasonable length
        # 2. Has numeric signal (always pass - vital signs, measurements, etc.)
        # 3. Has medical diagnosis term + reasonable length (diagnoses/findings)
        if (is_long_enough or has_numeric) and (has_verb or has_numeric or has_medical_term):
            has_signal = True
            
    # If all facts were boilerplate/legends, drop it
    if non_boilerplate_count == 0:
        return False
        
    return has_signal
