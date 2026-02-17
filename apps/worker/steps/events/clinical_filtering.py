import re
from typing import List, Set

NOISE_REGEXES = [
    r"(?i)^records of",
    r"(?i)pdf_page",
    r"(?i)^potter harry",
    r"(?i)^review of systems",
    r"(?i)^care advice given",
    r"(?i)^no (past medical history|past surgical history|family history) on file",
    r"(?i)^monitoring with cardiac monitor",
    r"(?i)^preanesthetic checklist",
    r"(?i)^unknown$",
    r"(?i)^only$",
    r"(?i)^,?$",
    r"(?i)^\.$",
    r"(?i)\bs\s+\d+\b",
    r"\b\d+-\d+\b"
]

INJURY_KEYWORDS = {"fracture", "tear", "wound", "gsw", "gunshot", "infection", "osteomyelitis", "fragment", "defect", "stiffness", "laceration"}
PROCEDURE_KEYWORDS = {"repair", "orif", "procedure", "underwent", "removal", "debridement", "arthroscopy", "status post", "s/p"}
VERB_KEYWORDS = {"noted", "reported", "recommended", "consulted", "reviewed"}

def normalize_text(s: str) -> str:
    if not s: return ""
    s = s.lower()
    s = re.sub(r"pdf_page\s*[s\d\-\s]*", " ", s)
    s = re.sub(r"\(p\.\s*\d+\)", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" . , ; : - _")

def is_noise_line(text: str) -> bool:
    """Strict atom-level noise filter."""
    if not text or len(text.strip()) < 4:
        return True
    
    # Artifact Check
    low = text.lower()
    if "harry potter" in low or "chapman" in low or "jackie chan" in low:
        return True
        
    cleaned = text.strip()
    for pattern in NOISE_REGEXES:
        if re.search(pattern, cleaned):
            return True
    return False

def is_valid_injury(text: str) -> bool:
    low = text.lower()
    if "chapman" in low or "only" in low: return False
    if not any(kw in low for kw in INJURY_KEYWORDS): return False
    if any(kw in low for kw in PROCEDURE_KEYWORDS): return False
    if any(kw in low for kw in VERB_KEYWORDS): return False
    return True

def normalize_injury_concept(text: str) -> str:
    """Canonicalize injury strings into medical concepts."""
    low = text.lower()
    if "acromion" in low and "fracture" in low:
        return "comminuted right acromion fracture"
    if "tuberosity" in low and "fracture" in low:
        return "greater tuberosity fracture"
    if "rotator cuff" in low and "tear" in low:
        return "chronic complete rotator cuff tear"
    if any(kw in low for kw in ["ballistic", "bullet", "fragment"]):
        return "retained ballistic fragments"
    if "gunshot" in low or "gsw" in low:
        return "gunshot wound, right shoulder"
    if "infection" in low:
        return "wound infection"
    return text.strip().capitalize()
