import re

# Some PDFs split date & time across two lines:
#   "9/24"
#   "1600 Admit to Oncology Floor..."
DATE_LINE_RE = re.compile(r"^\s*(\d{1,2})[/\-](\d{1,2})[\.\s]*$")
TIME_LINE_RE = re.compile(r"^\s*(\d{1,2}:?\d{2})\s*(.*)$")
DATE_TIME_LINE_RE = re.compile(r"^\s*(\d{1,2})[/\-](\d{1,2})\s+(\d{1,2}:?\d{2})\s*(.*)$")
DATE_TIME_INLINE_RE = re.compile(r"(?:\b|^)(\d{1,2})[/\-](\d{1,2})\s+(\d{1,2}:?\d{2})\b")

# Author / Signer patterns
AUTHOR_RE = re.compile(r"(?i)(?:^|[\-\s]{2,})([A-Z]\.\s*[A-Za-z]+|[A-Z]{2,3}),?\s*(RN|MD|LPN|DO|NP|PA)?\s*$")

CLINICAL_INDICATORS = [
    (r"(?i)\bpain\s*(?:level|score)?\s*:?\s*(\d{1,2}/10)\b", "Pain Level"),
    (r"(?i)diagnosis\s*:\s*([^.\n]+)", "Diagnosis"),
    (r"(?i)\b(adenocarcinoma|carcinoma|cancer|malignancy)\b", "Diagnosis"),
    (r"(?i)\b(vomiting|vomit|emesis|nausea)\b", "GI Symptom"),
    (r"(?i)\b(shortness of breath|sob|dyspnea)\b", "Respiratory Symptom"),
    (r"(?i)\b(cough|forceful coughing)\b", "Respiratory Symptom"),
    (r"(?i)\b(hospice|end of life)\b", "Care Planning"),
    (r"(?i)\b(dependent|assistance|requires help|requires partner)\b", "Functional Status"),
    (r"(?i)\b(discharge home|discharged to home)\b", "Disposition"),
    (r"(?i)\bwt\s*:\s*(\d{2,3})\b", "Weight"),
    (r"(?i)history\s*of\s*([^.\n]+)", "Medical History"),
    (r"(?i)\b(ambulated|ambulation|gait|walking|mobility)\b", "Mobility"),
    (r"(?i)\b(balance|fall risk|fall prevention)\b", "Fall Risk"),
    (r"(?i)\b(range of motion|rom|flexibility)\b", "Range of Motion"),
    (r"(?i)\b(transfer|transferring|bed mobility)\b", "Transfer"),
    (r"(?i)\b(walker|cane|assistive device|wheelchair)\b", "Assistive Device"),
    (r"(?i)\b(triage level|triage category|chief complaint|presenting complaint)\b", "Chief Complaint"),
    (r"(?i)\b(vital signs|bp|blood pressure|heart rate|temp|temperature|o2 sat)\b", "Vital Signs"),
]

def is_boilerplate_line(text: str) -> bool:
    """Hard drop deterministic boilerplate/admin lines."""
    n = " ".join(text.lower().split())
    if re.search(r"\b\d{1,2}[/\-]\d{1,2}\s+\d{1,2}:?\d{2}\b", text): return False
    if re.search(r"^\s*\d{1,2}:?\d{2}\b", text): return False
    if any(kw in n for kw in ["pain", "vomit", "oxycodone", "cough", "fall risk"]): return False
    if re.search(r",\s*rn\b", n):
        if len(re.sub(r"[^a-z]", "", n)) < 25: return True
    if re.match(r"^[_\-\s\*=]{3,}$", n): return True
    boilerplate_patterns = [
        r"national league for nursing", r"chart materials", r"patient chart", r"simulation",
        r"patient name\s*:", r"mrn\s*:", r"doctor name\s*:", r"dob\s*:",
        r"nurse signatures?", r"scheduled & routine drugs", r"allergies\s*:",
        r"medication administration record", r"intramuscular legend", r"subcutaneous site code",
        r"fluid measurements", r"sample measurements", r"time: site: initials",
        r"see nurs[ei]s? notes", r"see mar", r"pain type\s*:", r"pain interventions?\s*:",
        r"positioning\s*:", r"pt\. hygiene\s*:", r"wound assessment", r"wound drainage",
        r"wound care\s*:", r"braden scale", r"hourly", r"iv solution", r"rate ordered\s*:",
        r"date/time hung\s*:", r"intensity \(1-10/10\)", r"mucous membranes\s*:",
        r"iv site/rate", r"patient hygiene", r"po fluids", r"nurse initials",
        r"legend\s*\)", r"[a-z]=\s*[a-z]{4} ventrogluteal", r"\d=[a-z]{3} abdomen",
        r"hours to be given", r"^date\s*:\s*$", r"^medication\s*:\s*$",
        r"^vital signs record\s*$", r"^date of order\s*$", r"^date/time given\s*$",
        r"^weight\s*$", r"^respirations\s*$", r"^temp\s*$"
    ]
    return any(re.search(p, n) for p in boilerplate_patterns)
