from typing import List, Set, Dict, Any
from .synthesis_domain import ClinicalEvent
from .clinical_clustering import SURGERY
from .clinical_filtering import is_valid_injury, normalize_injury_concept

def get_total_surgeries(events: List[ClinicalEvent]) -> int:
    surg_dates = {e.date for e in events if e.event_type == SURGERY and e.procedures}
    return len(surg_dates)

def get_injury_summary(events: List[ClinicalEvent]) -> List[str]:
    """Builds injury list from normalized concept sets, ensuring validity and canonical form."""
    injuries = set()
    for e in events:
        for i in e.fractures.union(e.tears).union(e.fragments).union(e.infections):
            if is_valid_injury(i):
                norm = normalize_injury_concept(i)
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
    injury_terms = " ".join(i.lower() for i in get_injury_summary(events))
    if "gunshot" in injury_terms or "gsw" in injury_terms:
        mechanism = "Gunshot wound"
    elif "fall" in injury_terms:
        mechanism = "Fall-related injury"
    elif "mvc" in injury_terms or "motor vehicle" in injury_terms:
        mechanism = "Motor vehicle collision"

    return {
        "total_surgeries": get_total_surgeries(events),
        "treatment_timeframe": timeframe,
        "complications": sorted(list(complications)),
        "injuries": get_injury_summary(events),
        "mechanism": mechanism,
    }
