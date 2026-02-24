from typing import List, Set, Dict, Any
from .synthesis_domain import ClinicalEvent
from .clinical_clustering import SURGERY
from .clinical_filtering import is_valid_injury, normalize_injury_concept

def get_total_surgeries(events: List[ClinicalEvent]) -> int:
    surg_dates = {e.date for e in events if e.event_type == SURGERY and e.procedures}
    return len(surg_dates)

def get_injury_summary(events: List[ClinicalEvent]) -> List[str]:
    """Builds injury list from normalized concept sets, including diagnoses."""
    injuries = set()
    for e in events:
        # Include explicit fractures/tears
        for i in e.fractures.union(e.tears).union(e.fragments).union(e.infections):
            if is_valid_injury(i):
                norm = normalize_injury_concept(i)
                if norm:
                    injuries.add(norm.capitalize())
        
        # Include diagnoses (often contains ICD-10 clinical labels)
        for dx in (e.diagnoses or []):
            if is_valid_injury(dx):
                norm = normalize_injury_concept(dx)
                if norm:
                    injuries.add(norm.capitalize())
    
    return sorted(list(injuries))

def get_surgical_summary_rows(events: List[ClinicalEvent]) -> List[dict]:
    """Builds surgical summaries from canonical procedures."""
    rows = []
    for e in events:
        if e.event_type == SURGERY:
            if not e.procedures:
                continue
            # Findings from combined fractures/tears
            findings = sorted(list(e.fractures.union(e.tears)))
            
            rows.append({
                "date": str(e.date),
                "procedures": sorted(list(e.procedures)),
                "findings": findings,
                "citations": e.citations
            })
    return rows

def get_case_summary_data(events: List[ClinicalEvent]) -> Dict[str, Any]:
    dates = [e.date for e in events if e.date and e.date.year >= 1970]
    timeframe = f"{min(dates)} -> {max(dates)}" if dates else "Unknown"
    
    complications = set()
    for e in events:
        # Major findings as complications
        for t in e.tears:
            if "complete" in t or "massive" in t: complications.add(t.capitalize())
        if e.infections:
            complications.add("Wound infection")

    mechanism = "Not established from records"
    all_text = " ".join(a.text.lower() for e in events for a in e.atoms)
    
    if "gunshot" in all_text or "gsw" in all_text:
        mechanism = "Gunshot wound"
    elif "motor vehicle" in all_text or " mvc " in all_text or " mva " in all_text or "collision" in all_text:
        mechanism = "Motor vehicle collision"
    elif " fall" in all_text:
        mechanism = "Fall-related injury"
    elif "assault" in all_text:
        mechanism = "Assault"

    return {
        "total_surgeries": get_total_surgeries(events),
        "treatment_timeframe": timeframe,
        "complications": sorted(list(complications)),
        "injuries": get_injury_summary(events),
        "mechanism": mechanism,
    }
