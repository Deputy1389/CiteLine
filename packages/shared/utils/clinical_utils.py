"""
Shared Clinical Utilities - Canonicalization, sanitization, and report-quality guards.
"""
from __future__ import annotations
import re
from datetime import date
from typing import Iterable, Optional
from packages.shared.models import Event, EventType

UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
PAGE_ARTIFACT_RE = re.compile(r"\bs\s*\d+(?:-\d+)?\b", re.IGNORECASE)
NUM_TWO_ARTIFACT_RE = re.compile(r"\b\d{1,4}two\b", re.IGNORECASE)

_FORBIDDEN_TOKEN_RES = [
    re.compile(r"records\s+of\s+harry\s+potter", re.IGNORECASE),
    re.compile(r"potter\s+harry\s+lsu\s+client\s+provided\s+medicals", re.IGNORECASE),
    re.compile(r"client\s+provided\s+medicals", re.IGNORECASE),
    re.compile(r"pdf[_\s]*page", re.IGNORECASE),
    re.compile(r"printed\s+page\s*\d+", re.IGNORECASE),
    re.compile(r"\bchapman\b", re.IGNORECASE),
    re.compile(r"review\s+of\s+systems", re.IGNORECASE),
]

_PROCEDURE_PATTERNS = [
    ("orif", re.compile(r"\borif\b|open reduction (?:and|&) internal fixation", re.IGNORECASE)),
    ("rotator cuff repair", re.compile(r"rotator cuff repair", re.IGNORECASE)),
    ("bullet removal", re.compile(r"bullet (?:removal|excision)", re.IGNORECASE)),
    ("irrigation and debridement", re.compile(r"\bi\s*&\s*d\b|irrigation.*debrid|debridement", re.IGNORECASE)),
    ("hardware removal", re.compile(r"hardware removal|remove(?:d)? hardware", re.IGNORECASE)),
]

def sanitize_for_report(text: str) -> str:
    if not text: return ""
    cleaned = text
    for token_re in _FORBIDDEN_TOKEN_RES: cleaned = token_re.sub("", cleaned)
    cleaned = UUID_RE.sub("", cleaned)
    cleaned = PAGE_ARTIFACT_RE.sub("", cleaned)
    cleaned = NUM_TWO_ARTIFACT_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" .;,-")

_MIN_PLAUSIBLE_YEAR = 1800
_MAX_PLAUSIBLE_YEAR = 2500
_SENTINEL_YEARS = {1, 1900, 9999}


def is_placeholder_date(value: date | None) -> bool:
    if value is None:
        return True
    return value.year in _SENTINEL_YEARS or value.year < _MIN_PLAUSIBLE_YEAR or value.year >= 9000


def date_sanity(value: date | None) -> bool:
    if value is None:
        return False
    if is_placeholder_date(value):
        return False
    return _MIN_PLAUSIBLE_YEAR <= value.year <= _MAX_PLAUSIBLE_YEAR

def procedure_canonicalization(text: str) -> list[str]:
    return [label for label, pat in _PROCEDURE_PATTERNS if pat.search(text or "")]

def injury_canonicalization(text: str) -> list[str]:
    if not text: return []
    concepts = []
    if re.search(r"fracture", text, re.IGNORECASE): concepts.append("fracture")
    if re.search(r"tear", text, re.IGNORECASE): concepts.append("tear")
    return concepts
