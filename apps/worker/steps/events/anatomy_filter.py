import re
from typing import List, Set
from .synthesis_domain import ClinicalAtom

ANATOMY_DOMAINS = {
    "shoulder": {"shoulder", "acromion", "humerus", "tuberosity", "rotator cuff", "deltoid", "scapula", "clavicle"},
    "hip": {"hip", "femur", "trochanter", "acetabulum", "pelvis", "groin"},
    "knee": {"knee", "patella", "tibia", "fibula", "meniscus", "acl"},
    "spine": {"spine", "cervical", "thoracic", "lumbar", "vertebra", "disc"}
}

def infer_dominant_domain(atoms: List[ClinicalAtom]) -> str:
    counts = {domain: 0 for domain in ANATOMY_DOMAINS}
    for a in atoms:
        text = a.text.lower()
        for domain, terms in ANATOMY_DOMAINS.items():
            if any(term in text for term in terms):
                counts[domain] += 1
    
    # Return domain with max count, default to shoulder for this case
    dominant = max(counts, key=counts.get)
    if counts[dominant] == 0: return "shoulder"
    return dominant

def filter_anatomy_anomalies(atoms: List[ClinicalAtom], dominant_domain: str) -> List[ClinicalAtom]:
    filtered = []
    other_domains = [d for d in ANATOMY_DOMAINS if d != dominant_domain]
    
    for a in atoms:
        text = a.text.lower()
        is_anomaly = False
        
        # Check if line contains terms from other domains
        for domain in other_domains:
            if any(term in text for term in ANATOMY_DOMAINS[domain]):
                # If it has other domain term but NOT dominant domain term, it might be an anomaly
                if not any(term in text for term in ANATOMY_DOMAINS[dominant_domain]):
                    # Check frequency/confidence (Simplified: if it only appears in one atom type check?)
                    # For now, if it's "greater trochanteric" in a "shoulder" domain, it's a hard drop.
                    if "trochanter" in text and dominant_domain == "shoulder":
                        is_anomaly = True
                        break
        
        if not is_anomaly:
            filtered.append(a)
            
    return filtered
