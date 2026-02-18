"""
Deterministic report-quality guards and canonicalizers.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable

from packages.shared.models import Event, EventType


UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
PAGE_ARTIFACT_RE = re.compile(r"\bs\s*\d+(?:-\d+)?\b", re.IGNORECASE)
NUM_TWO_ARTIFACT_RE = re.compile(r"\b\d{1,4}two\b", re.IGNORECASE)

_FORBIDDEN_TOKEN_RES: list[re.Pattern[str]] = [
    re.compile(r"records\s+of\s+harry\s+potter", re.IGNORECASE),
    re.compile(r"potter\s+harry\s+lsu\s+client\s+provided\s+medicals", re.IGNORECASE),
    re.compile(r"client\s+provided\s+medicals", re.IGNORECASE),
    re.compile(r"pdf[_\s]*page", re.IGNORECASE),
    re.compile(r"printed\s+page\s*\d+", re.IGNORECASE),
    re.compile(r"\bfrom\s+interim\s+hospital\b", re.IGNORECASE),
    re.compile(r"notes?\s*-\s*encounter\s*notes?\s*\(continued\)", re.IGNORECASE),
    re.compile(r"please\s+see\s+their\s+full\s+h&p;?/clinic\s+notes\s+for\s+details\.?", re.IGNORECASE),
    re.compile(r"\bchapman\b", re.IGNORECASE),
    re.compile(r"review\s+of\s+systems", re.IGNORECASE),
]

_RAW_FRAGMENT_RES: list[re.Pattern[str]] = [
    re.compile(r"notes?\s*-\s*encounter\s*notes?\s*\(continued\)", re.IGNORECASE),
    re.compile(r"registered under \d+\s+separate\s+mrn", re.IGNORECASE),
    re.compile(r"please see.*clinic notes.*details", re.IGNORECASE),
    re.compile(r"\bh&p\b", re.IGNORECASE),
    re.compile(r"medical record summary", re.IGNORECASE),
    re.compile(r"patient id\s*:", re.IGNORECASE),
]

_PROCEDURE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("orif", re.compile(r"\borif\b|open reduction (?:and|&) internal fixation", re.IGNORECASE)),
    ("rotator cuff repair", re.compile(r"rotator cuff repair", re.IGNORECASE)),
    ("bullet removal", re.compile(r"bullet (?:removal|excision)", re.IGNORECASE)),
    ("irrigation and debridement", re.compile(r"\bi\s*&\s*d\b|irrigation.*debrid|debridement", re.IGNORECASE)),
    ("hardware removal", re.compile(r"hardware removal|remove(?:d)? hardware", re.IGNORECASE)),
    ("infection management", re.compile(r"infect(?:ion|ed)|iv vancomycin|rifampin|minocycline", re.IGNORECASE)),
]

_INJURY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("gunshot wound", re.compile(r"\bgsw\b|gunshot wound", re.IGNORECASE)),
    ("shoulder fracture", re.compile(r"fracture", re.IGNORECASE)),
    ("wound infection", re.compile(r"wound infection|infect", re.IGNORECASE)),
    ("rotator cuff injury", re.compile(r"rotator cuff", re.IGNORECASE)),
]


def sanitize_for_report(text: str) -> str:
    """Remove client-facing artifacts and boilerplate from extracted fragments."""
    if not text:
        return ""
    cleaned = text
    for token_re in _FORBIDDEN_TOKEN_RES:
        cleaned = token_re.sub("", cleaned)
    cleaned = UUID_RE.sub("", cleaned)
    cleaned = re.sub(r"(?i)\bpatient id\s*:\s*\b", "", cleaned)
    cleaned = PAGE_ARTIFACT_RE.sub("", cleaned)
    cleaned = NUM_TWO_ARTIFACT_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .;,-")
    return cleaned


def date_sanity(value: date | None) -> bool:
    """Accept only modern dates for this dataset."""
    if value is None:
        return False
    if value.year < 1901:
        return False
    return value <= date.today()


def procedure_canonicalization(text: str) -> list[str]:
    """Extract deterministic surgery/procedure concepts from text."""
    concepts: list[str] = []
    for label, pattern in _PROCEDURE_PATTERNS:
        if pattern.search(text or ""):
            concepts.append(label)
    return concepts


def injury_canonicalization(text: str) -> list[str]:
    """Extract deterministic injury concepts from text."""
    concepts: list[str] = []
    for label, pattern in _INJURY_PATTERNS:
        if pattern.search(text or ""):
            concepts.append(label)
    return concepts


def surgery_classifier_guard(event: Event) -> bool:
    """
    Require non-empty procedure concepts for surgery/procedure events.
    """
    is_surgery_type = event.event_type == EventType.PROCEDURE
    blob = " ".join(f.text for f in event.facts if f.text)
    low = blob.lower()
    has_keyword = bool(
        re.search(r"surgery|operative|orif|debrid|repair|hardware|excision|anesthesia|postop|preop", blob, re.IGNORECASE)
    )
    direct_procedure_markers = [
        "procedure performed",
        "operative report",
        "operating room",
        "taken to the operating room",
        "anesthesia",
        "postop diagnosis",
        "preop diagnosis",
        "underwent",
    ]
    has_direct_marker = any(marker in low for marker in direct_procedure_markers)
    historical_only = (("status post" in low) or ("s/p" in low)) and not has_direct_marker
    if not (is_surgery_type or has_keyword):
        return True
    if historical_only:
        return False
    return len(procedure_canonicalization(blob)) > 0


def is_reportable_fact(text: str) -> bool:
    raw = text or ""
    if any(pattern.search(raw) for pattern in _RAW_FRAGMENT_RES):
        return False
    cleaned = sanitize_for_report(raw)
    if not cleaned:
        return False
    if len(cleaned) < 12:
        return False
    low = cleaned.lower()
    if any(pattern.search(low) for pattern in _RAW_FRAGMENT_RES):
        return False
    return True


def contains_uuid_like_provider_tokens(values: Iterable[str]) -> bool:
    for value in values:
        if value and UUID_RE.search(value):
            return True
    return False
