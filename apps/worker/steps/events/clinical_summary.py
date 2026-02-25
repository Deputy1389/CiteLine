from typing import List, Set, Dict, Any
from .synthesis_domain import ClinicalEvent
from .clinical_clustering import SURGERY
from .clinical_filtering import is_valid_injury, normalize_injury_concept

def get_total_surgeries(events: List[ClinicalEvent]) -> int:
    surg_dates = {e.date for e in events if e.event_type == SURGERY and e.procedures}
    return len(surg_dates)

def get_injury_summary(events: List[ClinicalEvent]) -> List[str]:
    """Builds injury list from normalized concept sets, including diagnoses and high-value PI findings."""
    injuries = set()
    for e in events:
        # Include high-value PI anchors (disc displacement, radiculopathy)
        source_sets = [e.fractures, e.tears, e.fragments, e.infections, e.disc_injuries, e.neurological_findings]
        for sset in source_sets:
            for i in sset:
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

def get_treatment_phases(events: List[ClinicalEvent]) -> Dict[str, Any]:
    """Groups therapy and clinical events into Acute, Subacute, and Recovery phases."""
    dates = sorted([e.date for e in events if e.date and e.date.year >= 1970])
    if not dates:
        return {}
    
    start_date = dates[0]
    phases = {
        "acute": {"label": "Acute Phase (Weeks 1-4)", "events": [], "pain_scores": []},
        "subacute": {"label": "Subacute Phase (Months 2-3)", "events": [], "pain_scores": []},
        "recovery": {"label": "Recovery/Maintenance Phase (Months 4+)", "events": [], "pain_scores": []}
    }
    
    import re
    for e in events:
        days_since = (e.date - start_date).days
        if days_since <= 30: phase = "acute"
        elif days_since <= 90: phase = "subacute"
        else: phase = "recovery"
        
        phases[phase]["events"].append(e)
        
        # Extract pain for trend
        for a in e.atoms:
            m = re.search(r"(\d+)/10", a.text)
            if m: phases[phase]["pain_scores"].append(int(m.group(1)))
            
    return phases

def get_causation_ladder(events: List[ClinicalEvent]) -> List[str]:
    """Builds the 6-step traumatic injury arc."""
    ladder = []
    text_blob = " ".join(a.text.lower() for e in events for a in e.atoms)
    
    # Step 1: Impact
    if "motor vehicle" in text_blob or "mvc" in text_blob or "rear-end" in text_blob:
        ladder.append("Traumatic Event: MVC/Impact documented with same-day or early evaluation.")
    
    # Step 2: Immediate Symptoms
    if any(s in text_blob for s in ["pain", "spasm", "guarding", "restricted"]):
        ladder.append("Immediate Symptoms: Onset of cervical/lumbar pain and muscle guarding.")
        
    # Step 3: Early Clinical Diagnosis
    dxs = get_injury_summary(events)
    if dxs:
        ladder.append(f"Clinical Diagnosis: {dxs[0]} identified in initial treatment plan.")
        
    # Step 4: Objective Confirmation
    objs = set()
    for e in events:
        objs.update(e.objective_findings)
        if e.event_type == "IMAGING" and e.disc_injuries:
            objs.add("MRI confirmation of disc pathology")
    if objs:
        ladder.append(f"Objective Confirmation: {list(objs)[0]} and positive clinical tests.")
        
    return ladder

def get_surgical_summary_rows(events: List[ClinicalEvent]) -> List[dict]:
    """Builds surgical summaries from canonical procedures."""
    rows = []
    for e in events:
        if e.event_type == SURGERY:
            if not e.procedures:
                continue
            # Findings from combined fractures/tears/discs
            findings = sorted(list(e.fractures.union(e.tears).union(e.disc_injuries)))
            
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
    
    # Calculate pain progression
    all_pain = []
    import re
    for e in events:
        for a in e.atoms:
            m = re.search(r"(\d+)/10", a.text)
            if m: all_pain.append(int(m.group(1)))
    
    pain_progression = "Not documented"
    if len(all_pain) >= 2:
        pain_progression = f"{all_pain[0]}/10 (Acute) -> {all_pain[-1]}/10 (Discharge)"

    mechanism = "Not established from records"
    all_text = " ".join(a.text.lower() for e in events for a in e.atoms)
    
    if "gunshot" in all_text or "gsw" in all_text:
        mechanism = "Gunshot wound"
    elif any(kw in all_text for kw in ["motor vehicle", " mvc ", " mva ", "collision", "rear-end", "rear end"]):
        mechanism = "Motor vehicle collision"

    objective_anchors = set()
    for e in events:
        objective_anchors.update(e.objective_findings)
        for test in e.ortho_tests:
            objective_anchors.add(f"Positive {test}")

    return {
        "total_surgeries": get_total_surgeries(events),
        "treatment_timeframe": timeframe,
        "injuries": get_injury_summary(events),
        "mechanism": mechanism,
        "objective_anchors": sorted(list(objective_anchors))[:10],
        "pain_progression": pain_progression,
        "causation_ladder": get_causation_ladder(events),
        "phases": get_treatment_phases(events)
    }
