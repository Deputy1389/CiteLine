"""
Shared regex constants for export rendering.
"""
from __future__ import annotations

import re

INPATIENT_MARKER_RE = re.compile(
    r"\b(admission order|hospital day|inpatient service|discharge summary|admitted|inpatient|hospitalist|icu|intensive care)\b",
    re.IGNORECASE,
)
MECHANISM_KEYWORD_RE = re.compile(
    r"\b(mva|mvc|motor vehicle|collision|rear[- ]end|accident|fell|fall|slipped|slip and fall)\b",
    re.IGNORECASE,
)
PROCEDURE_ANCHOR_RE = re.compile(
    r"\b(depo-?medrol|lidocaine|fluoroscopy|complications:|interlaminar|transforaminal|epidural steroid injection|esi)\b",
    re.IGNORECASE,
)
DX_ALLOWED_SECTION_RE = re.compile(
    r"\b(impression|assessment|plan|clinical impression|diagnosis|diagnoses|problem list|preoperative diagnosis|postoperative diagnosis)\b",
    re.IGNORECASE,
)
DX_CODE_RE = re.compile(r"\b([A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?|[A-Z]\d{2}\.\d)\b")
DX_MEDICAL_TERM_RE = re.compile(
    r"\b(fracture|radiculopathy|protrusion|herniation|stenosis|infection|dislocation|tear|sprain|strain|pain|neuropathy|degeneration|spondylosis|wound)\b",
    re.IGNORECASE,
)
TOP10_LOW_VALUE_RE = re.compile(
    r"(i,\s*the undersigned|consent to the performance|risks?,\s*benefits?,\s*and alternatives?|"
    r"discharge summary\s+discharge summary|from:\s*\(\d{3}\)\s*\d{3}[-\d]+\s*to:\s*records dept|"
    r"risks?:.*alternatives?:)",
    re.IGNORECASE,
)
APPENDIX_DX_RELEVANT_RE = re.compile(
    r"\b("
    r"neck pain|cervical|low back pain|lumbar|thoracic|back pain|"
    r"strain|sprain|radiculopathy|sciatica|disc|herniation|protrusion|stenosis|"
    r"fracture|dislocation|myofascial|spasm|whiplash|cervicalgia|lumbago|paresthesia"
    r")\b",
    re.IGNORECASE,
)
APPENDIX_DX_EXCLUDE_RE = re.compile(
    r"\b(years ago|appendectomy|arthroscopy|no history of|reports no regular use of tobacco)\b",
    re.IGNORECASE,
)

WORD_SALAD_TOKEN_RE = re.compile(
    r"\b(career|business|debate|marketing|finance|celebrity|fashion|politics|social media|mission|hotel|magazine|government board|professional eye|peace around)\b",
    re.IGNORECASE,
)
MEDICAL_ANCHOR_RE = re.compile(
    r"\b(assessment|impression|diagnosis|plan|mri|x-?ray|ct|ed|emergency|pain\s*\d+\s*/\s*10|rom|range of motion|strength|radiculopathy|herniation|stenosis|fracture|sprain|strain|injection|procedure|surgery|epidural|fluoroscopy|depo-?medrol|lidocaine|therapy|pt|icd-?10|discharge|admission)\b",
    re.IGNORECASE,
)
META_LANGUAGE_RE = re.compile(
    r"\b(identified from source|identified|documented in cited records|markers|extracted|encounter identified|not stated in records|documented)\b",
    re.IGNORECASE,
)
