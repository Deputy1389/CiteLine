import re

_FAX_HEADER_PATTERNS = [
    re.compile(r"^FROM:\s*\(", re.I),
    re.compile(r"^TO:\s*(RECORDS|FAX|DEPT)", re.I),
    re.compile(r"\bPAGE:\s*\d+\s*$", re.I | re.M),
    re.compile(r"^\(\d{3}\)\s*\d{3}-\d{4}", re.I),
    re.compile(r"\bRECORDS\s+DEPT\b", re.I),
    re.compile(r"\bCONFIDENTIAL.*FAX\b", re.I),
]


def is_fax_header_noise(text: str) -> bool:
    """Return True if text matches fax transmission header patterns."""
    stripped = (text or "").strip()
    return any(p.search(stripped) for p in _FAX_HEADER_PATTERNS)


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
    if is_fax_header_noise(text):
        return True
    return False

def is_flowsheet_noise(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    tokens = re.findall(r"[a-z0-9:/.-]+", low)
    token_count = len(tokens)
    head_tokens = tokens[:300]
    timestamp_hits = len(re.findall(r"\b([01]?\d|2[0-3]):[0-5]\d(?:[:][0-5]\d)?\b", low))
    head_timestamp_hits = sum(1 for t in head_tokens if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d(?:[:][0-5]\d)?", t))
    time_like_hits = sum(1 for t in tokens if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d(?:[:][0-5]\d)?|(?:\d{1,3}/\d{1,3})|\d+(?:\.\d+)?", t))
    numeric_time_ratio = (time_like_hits / max(1, token_count)) if token_count else 0.0
    short_lines = [ln.strip() for ln in re.split(r"[\n\r]+", text) if ln.strip()]
    many_short = sum(1 for ln in short_lines if len(ln.split()) <= 6) >= 10
    short_phrase_counts: dict[str, int] = {}
    for ln in short_lines:
        phrase = re.sub(r"\s+", " ", ln.lower()).strip(" :.-")
        if not phrase:
            continue
        if 1 <= len(phrase.split()) <= 4:
            short_phrase_counts[phrase] = short_phrase_counts.get(phrase, 0) + 1
    repeated_short_phrase = any(n >= 8 for n in short_phrase_counts.values())
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
    timestamp_grid = head_timestamp_hits >= 20
    mostly_numeric_time = token_count >= 40 and numeric_time_ratio > 0.50
    low_signal_repetitive = repeated_short_phrase and medical_tokens < 4 and len(short_lines) >= 8
    legacy_flowsheet = timestamp_hits >= 8 and many_short and medical_tokens < 3
    low_signal_dense = len(words) >= 30 and nonsense_ratio > 0.6 and medical_tokens < 3
    return timestamp_grid or mostly_numeric_time or low_signal_repetitive or legacy_flowsheet or low_signal_dense


def has_narrative_sentence(text: str) -> bool:
    if not text:
        return False
    for raw in re.split(r"[\n\r]+", text):
        line = (raw or "").strip()
        if not line:
            continue
        alpha_tokens = re.findall(r"[A-Za-z]{2,}", line)
        if len(alpha_tokens) < 8:
            continue
        if line.endswith("."):
            return True
        if re.search(r"\b(reports?|denies|exam|assessment|impression|diagnosis|plan|presented|complains?)\b", line, re.I):
            return True
    return False
