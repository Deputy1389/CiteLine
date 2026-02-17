from __future__ import annotations
import re
from datetime import date
from packages.shared.models import Page, Patient, Warning

def extract_demographics(pages: list[Page]) -> tuple[Patient, list[Warning]]:
    """
    Extract patient name, mrn, sex, age, and DOB from pages.
    """
    warnings: list[Warning] = []
    
    # Resolution state
    name_votes: dict[str, int] = {}
    mrn_votes: dict[str, int] = {}
    sex_votes: dict[str, int] = {"male": 0, "female": 0}
    age_candidates: list[int] = []
    
    # ── Extraction Patterns ───────────────────────────────────────────
    name_pattern = r"(?i)patient\s*name\s*:\s*([^,\n\r\t]+)"
    mrn_pattern = r"(?i)mrn\s*:\s*([A-Z0-9-]+)"
    # Narrative: "65-year-old female", "65yo M", "65 y/o woman"
    narrative_pattern = r"\b(\d{1,2})\s*(?:-|year old|yo|y/o|year-old)\s*(male|female|woman|man|m\b|f\b)\b"
    
    # Header Patterns
    sex_header_pattern = r"(?i)sex\s*:\s*(m|f|male|female)\b"
    age_header_pattern = r"(?i)age\s*:\s*(\d{1,3})\b"
    dob_header_pattern = r"(?i)dob\s*:\s*(\d{4}|(?:\d{1,2}[/-]){2}\d{2,4})\b"
    
    for page in pages:
        text = page.text
        
        # 1. Name extraction
        for m in re.finditer(name_pattern, text):
            name = m.group(1).strip()
            if len(name) > 3 and len(name) < 50:
                name_votes[name] = name_votes.get(name, 0) + 10
                
        # 2. MRN extraction
        for m in re.finditer(mrn_pattern, text):
            mrn = m.group(1).strip()
            mrn_votes[mrn] = mrn_votes.get(mrn, 0) + 10

        # 3. Narrative extraction
        for m in re.finditer(narrative_pattern, text, re.IGNORECASE):
            age_candidates.append(int(m.group(1)))
            sex_raw = m.group(2).lower()
            if sex_raw in ["female", "woman", "f"]:
                sex_votes["female"] += 10
            else:
                sex_votes["male"] += 10
                
        # 2. Header extraction (Medium weight)
        for m in re.finditer(sex_header_pattern, text):
            sex_raw = m.group(1).lower()
            if sex_raw in ["female", "f"]:
                sex_votes["female"] += 5
            else:
                sex_votes["male"] += 5
                
        for m in re.finditer(age_header_pattern, text):
            age_candidates.append(int(m.group(1)))
            
        for m in re.finditer(dob_header_pattern, text):
            dob_raw = m.group(1)
            # Try to parse YYYY or MM/DD/YYYY
            if len(dob_raw) == 4:
                try: age_candidates.append(date.today().year - int(dob_raw)) # Rough
                except: pass

    # ── Name Patterns (Low weight heuristic) ──────────────────────────
    female_names = ["julia", "mary", "linda", "patricia", "elizabeth"]
    male_names = ["robert", "john", "michael", "william", "david"]
    for page in pages:
        text_low = page.text.lower()
        if any(n in text_low for n in female_names):
            sex_votes["female"] += 1
        if any(n in text_low for n in male_names):
            sex_votes["male"] += 1

    # ── Resolution ────────────────────────────────────────────────────
    resolved_name = None
    if name_votes:
        resolved_name = max(name_votes.items(), key=lambda x: x[1])[0]
        
    resolved_mrn = None
    if mrn_votes:
        resolved_mrn = max(mrn_votes.items(), key=lambda x: x[1])[0]

    resolved_sex = None
    confidence = 0
    total_votes = sum(sex_votes.values())
    
    if total_votes > 0:
        if sex_votes["female"] > sex_votes["male"]:
            resolved_sex = "female"
            confidence = min(95, int((sex_votes["female"] / total_votes) * 100))
        elif sex_votes["male"] > sex_votes["female"]:
            resolved_sex = "male"
            confidence = min(95, int((sex_votes["male"] / total_votes) * 100))
        else:
            resolved_sex = "uncertain"
            confidence = 50

    # Age resolution: simple median or frequent value
    resolved_age = None
    if age_candidates:
        # Filter out reasonable ages
        valid_ages = [a for a in age_candidates if 0 <= a <= 120]
        if valid_ages:
            resolved_age = sorted(valid_ages)[len(valid_ages)//2]

    # DOB extraction (just for anchor inference if needed)
    resolved_dob = None
    # Re-scan for DOB specifically to get a date object if possible
    dob_pattern = r"(?i)dob\s*:\s*(\d{4})\b"
    for page in pages:
        m = re.search(dob_pattern, page.text)
        if m:
            try:
                resolved_dob = date(int(m.group(1)), 1, 1) # Jan 1 of that year
                break
            except: pass

    return Patient(
        name=resolved_name,
        mrn=resolved_mrn,
        sex=resolved_sex,
        age=resolved_age,
        dob=resolved_dob,
        sex_confidence=confidence,
    ), warnings
