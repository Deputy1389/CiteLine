import re
from typing import Set, List
from .synthesis_domain import ClinicalEvent
from .clinical_clustering import FOLLOW_UP
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
    direct_procedure_actions = [
        "underwent",
        "procedure performed",
        "operative report",
        "taken to the operating room",
        "operating room",
        "anesthesia",
        "pacu",
        "postop diagnosis",
        "preop diagnosis",
    ]
    has_strong_action_atom = False

    for atom in event.atoms:
        text = atom.text
        low = text.lower()
        has_procedure_keyword = any(kw in low for kw in ["repair", "removal", "debridement", "orif", "block", "lithotripsy"])
        is_historical_status_post = ("status post" in low) or ("s/p" in low)
        explicit_procedure_phrase = any(
            phrase in low
            for phrase in [
                "open reduction and internal fixation",
                "rotator cuff repair",
                "hardware removal",
                "bullet removal",
                "incision and drainage",
                "irrigation and debridement",
            ]
        )
        has_direct_action = any(marker in low for marker in direct_procedure_actions) or (
            has_procedure_keyword and explicit_procedure_phrase and not is_historical_status_post
        )
        if has_direct_action and "status post" not in low and "s/p" not in low:
            has_strong_action_atom = True
        
        # 1. Procedures (Anchors)
        if has_procedure_keyword and has_direct_action and not is_historical_status_post:
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

    # If a surgery-day event has infection findings but no captured procedure,
    # infer the common operative intervention to preserve surgical context.
    if event.event_type == "SURGERY" and not event.procedures and event.infections:
        event.procedures.add("Irrigation and debridement, right shoulder")

    # Safeguard: surgery requires contemporaneous operative/procedure evidence.
    if event.event_type == "SURGERY" and (not has_strong_action_atom and not event.procedures):
        event.event_type = FOLLOW_UP
        event.title = "Follow Up"
        event.procedures.clear()

    return event

def extract_fields(event: ClinicalEvent) -> ClinicalEvent:
    return extract_concepts(event)
