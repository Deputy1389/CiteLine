import re

def is_vitals_heavy(text: str) -> bool:
    low = text.lower()
    vital_markers = [
        "body height",
        "body weight",
        "bmi",
        "blood pressure",
        "heart rate",
        "respiratory rate",
        "pain severity",
        "head occipital-frontal circumference",
    ]
    return sum(1 for marker in vital_markers if marker in low) >= 2

def is_header_noise_fact(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return True
    if re.search(r"\bpatient\s*:\s*.+\bmrn\d*\b", low) and re.search(r"\bdate\s*:\s*\d{4}-\d{2}-\d{2}\b", low):
        if not re.search(
            r"\b(chief complaint|hpi|history of present illness|assessment|diagnosis|impression|plan|pain|rom|range of motion|strength|procedure|injection|medication|work status|work restriction)\b",
            low,
        ):
            return True
    if re.fullmatch(r"\s*(patient|name|mrn|date)\s*[:\-].*", low):
        return True
    if re.search(r"\bsee patient header\b", low):
        return True
    if re.search(r"\b(confidential medical record|protected health information|confidential.*hipaa)\b", low):
        return True
    if re.search(r"\bfax\s*(id|#)\s*:", low):
        return True
    if re.search(r"^type of case\s*$", low) or re.search(r"^personal injury\s*/\s*mva\s*$", low):
        return True
    return False

def is_flowsheet_noise(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    timestamp_hits = len(re.findall(r"\b([01]?\d|2[0-3]):[0-5]\d\b", low))
    short_lines = [ln.strip() for ln in re.split(r"[\n\r]+", text) if ln.strip()]
    many_short = sum(1 for ln in short_lines if len(ln.split()) <= 6) >= 10
    medical_tokens = len(
        re.findall(
            r"\b(impression|assessment|diagnosis|fracture|tear|infection|mri|x-?ray|rom|strength|pain|medication|injection|procedure|discharge|admission)\b",
            low,
        )
    )
    words = re.findall(r"[a-z]+", low)
    if not words:
        return False
    known_med = {
        "impression", "assessment", "diagnosis", "fracture", "tear", "infection", "mri", "xray", "rom", "strength",
        "pain", "medication", "injection", "procedure", "discharge", "admission", "cervical", "lumbar", "thoracic",
        "radicular", "follow", "therapy", "plan", "patient",
    }
    med_like = sum(1 for w in words if w in known_med)
    nonsense_ratio = 1.0 - (med_like / max(1, len(words)))
    return (timestamp_hits >= 8 and many_short and medical_tokens < 3) or (
        len(words) >= 30 and nonsense_ratio > 0.6 and medical_tokens < 3
    )
