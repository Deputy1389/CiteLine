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
    "complained", "denies", "vomited", "ambulated", "assisted", 
    "administered", "medicated", "discharged", "admitted", 
    "coughing", "repositioned", "ate", "requested", "vomit", "emesis", "nausea"
]

NUMERIC_SIGNALS = [
    r"\d{1,2}/10",  # Pain score (X/10)
    r"\d{2,3}\s*lbs?",  # Weight values
    r"\d{1,4}\s*(?:mg|ml|g|mcg|unit)",  # Medication dose
    r"(?i)\b(?:bp|temp|hr|rr|o2|sat)\b",  # Vital signs labels
]

def is_clinical_signal_event(event: Event) -> bool:
    """
    Returns True if the event contains meaningful clinical signal.
    Drops events that are only scaffolding, legends, or template text.
    """
    if not event.facts:
        return False

    # Admission and Discharge are always signals
    if event.event_type in [EventType.HOSPITAL_ADMISSION, EventType.HOSPITAL_DISCHARGE]:
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
        
        # Requirement: Length rule
        # lines shorter than 15 characters UNLESS they contain numeric clinical value
        is_long_enough = len(text) >= 15
        
        if (is_long_enough or has_numeric) and (has_verb or has_numeric):
            has_signal = True
            
    # If all facts were boilerplate/legends, drop it
    if non_boilerplate_count == 0:
        return False
        
    return has_signal
