import re
import logging
from typing import Optional
from packages.shared.models import Fact, FactKind

logger = logging.getLogger(__name__)

# JUNK patterns to DROP (case-insensitive)
JUNK_PATTERNS = [
    r"(?i)^(see nursing notes|see mar)$",
    r"(?i)^(MUSCULOSKELETAL|GENITOURINARY|FEMALES|MALES|HAND GRIPS|AMPUTATION|LOCATION|GENERAL APPEARANCE):?$",
    r"(?i)^(APPEARANCE OF URINE|Vital Signs Record|PRN Medications|Scheduled & Routine Drugs):?$",
    r"(?i)^(Date|Date/Time|Date Admitted|Date of|Date of Order|Date/Time Given):?$",
    r"(?i)^[A-F]=[RL]\s+.*(Deltoid|Thigh|abdomen|ventrogluteal).*",
    r".*_{3,}.*", # Placeholder underscores
    r"^[_\s\-]+$", # Pure punctuation/blanks
    r"^[a-z]=\s+[a-z]+.*", # Legend codes like "a= assist bath"
    r"©|National League", # Copyright
    r"(?i)\bnausea/vomiti$", # Only drop if it actually ends in 'vomiti'
]

# TRUNCATION signals
TRUNCATED_SUFFIXES = ("with", "conc", "vomiti", "assess", "consider doing a", "the", "of", "and", "to", "for")

# STRONG clinical signal tokens
STRONG_SIGNAL_REGEX = [
    r"\b\d{1,2}/10\b", # Pain
    r"vomit|emesis|nausea",
    r"cough|sob|shortness of breath",
    r"ambulated|assist|bathroom|toilet|voided|bath",
    r"medicated|administered|oxycodone|phenergan|ibuprofen|\d+\s*mg\b",
    r"discharge|admitted|orders received",
    r"fall risk|score:\s*\d+",
    r"\b(?:bp|temp|hr|rr|o2|wt|weight)\b.*\d+",
]

def clean_and_validate_facts(facts: list[Fact]) -> list[Fact]:
    """
    Cleans facts, merges wrapped lines, and drops junk/truncations.
    Also handles row splitting if multiple clinical points are joined.
    """
    if not facts:
        return []

    # 1. Row splitting & Normalization
    split_facts = []
    for f in facts:
        # Split on multiple spaces or specific delimiters that look like table joins
        # e.g. "Fact 1 -------------------Fact 2"
        sub_texts = re.split(r"\s{3,}|-{5,}", f.text)
        for t in sub_texts:
            t = " ".join(t.split()).strip()
            if not t: continue
            
            # Junk check
            t_up = t.upper()
            is_junk = False
            if any(j in t_up for j in ["SEE NURSING NOTES", "APPEARANCE OF URINE", "FEMALES: LMP"]):
                is_junk = True
            if "NAUSEA/VOMITI" in t_up and not t_up.endswith("NG"):
                 # if it ends in NG it is valid vomiting
                 is_junk = True
            
            if is_junk: continue

            # Check for author signature IN THE MIDDLE of a line and split it
            # e.g. "Patient is stable. T. Smyth, RN"
            sig_match = re.search(r"([A-Z]\.\s*[A-Z][a-z-]+),\s*(RN|LVN|LPN|MD|DO|PA-C|NP)\b", t)
            if sig_match and sig_match.start() > 5:
                before = t[:sig_match.start()].strip()
                after = t[sig_match.start():].strip()
                if before: split_facts.append(_derive_fact(f, before))
                if after: split_facts.append(_derive_fact(f, after))
            else:
                split_facts.append(_derive_fact(f, t))

    # 2. Merge line continuations
    merged_facts = []
    current = None
    
    for f in split_facts:
        if current is None:
            current = f
            continue
            
        t = current.text
        is_wrapped = False
        if t.endswith("-"):
            is_wrapped = True
        elif not any(t.endswith(p) for p in (".", "!", "?", ":", ";")):
            if f.text and f.text[0].islower():
                is_wrapped = True
            elif len(t) < 40 and ":" not in t:
                is_wrapped = True
                
        if is_wrapped:
            joiner = "" if t.endswith("-") else " "
            if t.endswith("-"): t = t[:-1]
            current.text = t + joiner + f.text
            existing = set(current.citation_ids)
            for cid in f.citation_ids:
                if cid not in existing:
                    current.citation_ids.append(cid)
        else:
            merged_facts.append(current)
            current = f
            
    if current:
        merged_facts.append(current)

    # 3. Stitch Quotes
    stitched = _stitch_quotes_in_facts(merged_facts)

    # 4. Final filter pass
    final = []
    for f in stitched:
        text = f.text
        # Drop JUNK
        if any(re.search(p, text) for p in JUNK_PATTERNS):
            continue
            
        # Drop TRUNCATED
        text_low = text.lower()
        if text_low.endswith(TRUNCATED_SUFFIXES) and len(text) < 100:
            continue
            
        # Drop dangling header fragments
        if re.search(r"(?i)^(MUSCULOSKELETAL|GENITOURINARY|FEMALES|MALES):?\s*$", text):
            continue

        # Drop weak/short
        has_signal = any(re.search(p, text, re.I) for p in STRONG_SIGNAL_REGEX)
        is_quote = '"' in text or "States " in text
        
        if not has_signal and not is_quote:
            if len(text) < 40 and not any(text.endswith(p) for p in (".", "!", "?")):
                continue
            if len(text) < 15:
                continue
                
        final.append(f)
        
    return final

def _derive_fact(original: Fact, new_text: str) -> Fact:
    return Fact(
        text=new_text,
        kind=original.kind,
        verbatim=original.verbatim,
        citation_id=original.citation_id,
        citation_ids=original.citation_ids,
        confidence=original.confidence
    )

def _stitch_quotes_in_facts(facts: list[Fact]) -> list[Fact]:
    """Combine lines that form a single quote."""
    if not facts: return []
    
    stitched = []
    buffer_fact = None
    in_quote = False
    
    for f in facts:
        text = f.text
        starts_quote = '"' in text or "States “" in text or 'States "' in text
        
        if starts_quote and not in_quote:
            in_quote = True
            buffer_fact = f
            if text.count('"') >= 2 or (text.count('“') > 0 and text.count('”') > 0):
                in_quote = False
                stitched.append(buffer_fact)
                buffer_fact = None
        elif in_quote:
            buffer_fact.text += " " + text
            existing = set(buffer_fact.citation_ids)
            for cid in f.citation_ids:
                if cid not in existing:
                    buffer_fact.citation_ids.append(cid)
            
            if '"' in text or '”' in text or any(text.endswith(p) for p in (".", "!", "?")):
                in_quote = False
                stitched.append(buffer_fact)
                buffer_fact = None
        else:
            stitched.append(f)
            
    if buffer_fact:
        stitched.append(buffer_fact)
        
    return stitched

def extract_author(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extracts name and role from signature lines.
    Validates against denylist.
    """
    DENYLIST = {"She", "He", "Patient", "Partner", "Doctor", "The", "It", "They", "This", "Her", "His", "She’s", "He’s", "There"}
    
    # Pattern 1: T. Smyth, RN (with optional trailing punctuation from OCR)
    # Allows for prefix text or dashes
    m1 = re.search(r"(?:^|[\-\s]{2,})([A-Z]\.\s*[A-Z][a-z-]+),\s*(RN|LVN|LPN|MD|DO|PA-C|NP|RN\.)\b", text)
    if m1:
        name, role = m1.group(1), m1.group(2)
        if name not in DENYLIST:
            return name, role.replace(".", "")

    # Pattern 2: Maria Reyes, RN
    m2 = re.search(r"(?:^|[\-\s]{2,})([A-Z][a-z-]+\s+[A-Z][a-z-]+),\s*(RN|MD|DO|PA-C|NP)\b", text)
    if m2:
        name, role = m2.group(1), m2.group(2)
        if name.split()[0] not in DENYLIST:
            return name, role

    return None, None
