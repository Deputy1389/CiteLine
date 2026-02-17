from typing import List
from datetime import date as date_type
from .synthesis_domain import ClinicalAtom, ClinicalEvent
from .clinical_filtering import is_noise_line, normalize_text

# Event Types
SURGERY = "SURGERY"
IMAGING = "IMAGING"
WOUND_CARE = "WOUND_CARE"
THERAPY_REHAB = "THERAPY_REHAB"
FOLLOW_UP = "FOLLOW_UP"
PREOPERATIVE_NOTE = "PREOPERATIVE_NOTE"
OTHER = "OTHER"

def classify_event(atoms: List[ClinicalAtom]) -> str:
    text_blob = " ".join([a.text.lower() for a in atoms])
    
    # Priority 1: SURGERY (Strict Guard)
    surgery_anchors = [
        "operative report", "procedure performed", "incision", 
        "anesthesia", "repair performed", "pacu", "operating room"
    ]
    has_surgery_anchor = any(anchor in text_blob for anchor in surgery_anchors)
    
    # Priority 2: IMAGING
    imaging_anchors = ["x-ray", "xr", "ct", "cta", "mri", "impression", "radiology"]
    has_imaging_anchor = any(anchor in text_blob for anchor in imaging_anchors)

    if has_surgery_anchor:
        # Guard: do not classify follow-up/status-post narratives as surgery unless
        # there is active OR/procedure context.
        followup_anchors = ["follow up", "clinic", "evaluation", "status post", "s/p", "post op", "suture removal"]
        strong_or_anchors = [
            "operative report",
            "procedure performed",
            "anesthesia",
            "operating room",
            "incision",
            "closure",
            "pacu",
            "postop diagnosis",
            "preop diagnosis",
        ]
        has_followup_context = any(anchor in text_blob for anchor in followup_anchors)
        has_strong_or_context = any(anchor in text_blob for anchor in strong_or_anchors)
        if has_followup_context and not has_strong_or_context:
            return FOLLOW_UP
        # Safety: downgrade to IMAGING if text is primarily imaging phrasing
        imaging_phrases = ["appeared located", "visualized", "no evidence of"]
        if any(p in text_blob for p in imaging_phrases) and not "incision" in text_blob:
             return IMAGING
        return SURGERY
        
    if has_imaging_anchor:
        return IMAGING

    # Priority 3: PREOPERATIVE_NOTE
    preop_anchors = ["pre-operative", "preoperative", "catheter", "consented", "anesthesia consultation"]
    if any(anchor in text_blob for anchor in preop_anchors):
        return PREOPERATIVE_NOTE
        
    # Priority 4: FOLLOW_UP
    followup_anchors = ["follow up", "clinic", "evaluation", "post op", "suture removal"]
    if any(anchor in text_blob for anchor in followup_anchors):
        return FOLLOW_UP
        
    return OTHER

def cluster_atoms_into_events(atoms: List[ClinicalAtom]) -> List[ClinicalEvent]:
    from collections import defaultdict
    # STEP 1: Strict atom-level noise filter before any processing
    cleaned = [a for a in atoms if not is_noise_line(a.text)]
    
    by_date = defaultdict(list)
    for a in cleaned:
        if a.date and isinstance(a.date, date_type) and a.date.year >= 1970:
            by_date[a.date].append(a)
        
    events = []
    for day in sorted(by_date.keys()):
        day_atoms = by_date[day]
        etype = classify_event(day_atoms)
        
        # Resolve provider
        providers = [a.provider for a in day_atoms if a.provider]
        provider = max(set(providers), key=providers.count) if providers else "Unknown Provider"
        
        # Merge citations
        all_cits = []
        seen = set()
        for a in day_atoms:
            for c in a.citations:
                if (c.doc_id, c.page) not in seen:
                    all_cits.append(c)
                    seen.add((c.doc_id, c.page))
                    
        events.append(ClinicalEvent(
            date=day,
            event_type=etype,
            title=etype.replace("_", " ").title(),
            atoms=day_atoms, # Strictly uses filtered atoms
            citations=all_cits,
            provider=provider
        ))
    return events
