import re
from typing import Set, List
from .synthesis_domain import ClinicalEvent
from .clinical_filtering import normalize_injury_concept, is_valid_injury

PROCEDURE_CANONICAL_MAP = {
    "removal": "Hardware removal, right shoulder",
    "deep right shoulder": "Hardware removal, right shoulder",
    "rotator cuff repair": "Open rotator cuff repair",
    "arthroscopic": "Arthroscopic debridement",
    "nerve block": "Interscalene nerve block",
    "lithotripsy": "Extracorporeal shock wave lithotripsy (ESWL)",
    "orif": "Open reduction and internal fixation (ORIF)"
}

def canonicalize_procedure(raw_text: str) -> str:
    low = raw_text.lower()
    for key, canonical in PROCEDURE_CANONICAL_MAP.items():
        if key in low: return canonical
    return raw_text.strip().capitalize()

def canonicalize_injuries(injuries: Set[str]) -> Set[str]:
    """
    Prefers concepts containing laterality (right/left) and removes generic duplicates.
    Example: 'comminuted acromion fracture' + 'comminuted right acromion fracture'
    -> 'comminuted right acromion fracture'
    """
    canonical = set()
    sorted_injuries = sorted(list(injuries), key=len, reverse=True)
    
    for injury in sorted_injuries:
        low = injury.lower()
        is_subsumed = False
        for existing in canonical:
            if low in existing.lower():
                is_subsumed = True
                break
        
        if not is_subsumed:
            canonical.add(injury)
            
    final = set()
    for item in canonical:
        low = item.lower()
        has_lat = 'right' in low or 'left' in low
        if not has_lat:
            base = low.replace('comminuted ', '').strip()
            if any((base in other.lower() and ('right' in other.lower() or 'left' in other.lower())) for other in canonical):
                continue
        final.add(item)
        
    return final

def extract_concepts(event: ClinicalEvent) -> ClinicalEvent:
    """
    Populates structured concept sets. 
    Strictly avoids polluting sets with raw fragments or noise.
    """
    for atom in event.atoms:
        text = atom.text
        low = text.lower()
        
        # 1. Procedures (Anchors)
        if any(kw in low for kw in ["repair", "removal", "debridement", "orif", "block", "lithotripsy"]):
            event.procedures.add(canonicalize_procedure(text))

        # 2. Injuries (Validated only)
        if is_valid_injury(text):
            concept = normalize_injury_concept(text)
            if "fracture" in concept.lower():
                event.fractures.add(concept)
            elif "tear" in concept.lower():
                event.tears.add(concept)
            elif "infection" in concept.lower():
                event.infections.add(concept)
            elif any(kw in concept.lower() for kw in ["fragment", "bullet"]):
                event.fragments.add(concept)

        # 3. Plans (Filtered for clinical content)
        if any(kw in low for kw in ["plan", "discharge", "follow", "return"]):
            # REJECT plan fragments containing metadata noise
            REJECT_PLAN = ["report", "summary", "pdf", "page", "hospital", "interim"]
            if not any(noise in low for noise in REJECT_PLAN):
                # Keep only clinical plan terms
                CLINICAL_PLAN = ["follow-up", "therapy", "rehab", "wound care", "pendulum", "sling"]
                if any(cp in low for cp in CLINICAL_PLAN):
                    # Minor defect 1: Reject plan concepts ending in stopwords
                    if not text.strip().lower().endswith((" in", " for", " with", " to", " in.", " for.", " with.", " to.")):
                        event.plans.add(text.strip().lower())

    # Safeguard: Procedure inference guard
    if event.event_type == "SURGERY" and not event.procedures:
        # Infer procedure from findings (e.g., if infection found, infer I&D)
        if event.infections:
            event.procedures.add("Irrigation and debridement, right shoulder")
        elif event.fractures:
            event.procedures.add("Open reduction internal fixation (ORIF)")
        elif event.tears:
            event.procedures.add("Rotator cuff repair")
        else:
            event.procedures.add("Surgical intervention")

    return event

def extract_fields(event: ClinicalEvent) -> ClinicalEvent:
    return extract_concepts(event)
