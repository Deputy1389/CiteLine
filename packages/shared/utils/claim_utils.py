from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Iterable

_BODY_REGION_PATTERNS = [
    ("cervical", re.compile(r"\b(cervical|neck|c[3-7]-?c?[3-7]?)\b", re.IGNORECASE)),
    ("lumbar", re.compile(r"\b(lumbar|low back|l[1-5]-?s?1?|back pain)\b", re.IGNORECASE)),
    ("thoracic", re.compile(r"\b(thoracic|mid back|t[1-2]?-?t?[1-2]?)\b", re.IGNORECASE)),
    ("shoulder", re.compile(r"\bshoulder\b", re.IGNORECASE)),
    ("knee", re.compile(r"\bknee\b", re.IGNORECASE)),
]


def parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", str(value))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def stable_id(parts: Iterable[str]) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def extract_body_region(text: str) -> str:
    raw = text or ""
    low = raw.lower()

    # Primary path: ontology concepts when available.
    try:
        from apps.worker.lib.targeted_ontology import extract_concepts

        for hit in extract_concepts(raw):
            canon = str(hit.canonical or "").lower()
            if "cervical" in canon or "neck" in canon or "whiplash" in canon:
                return "cervical"
            if "lumbar" in canon or "low back" in canon or "lumbago" in canon or canon == "back pain":
                return "lumbar"
            if "thoracic" in canon or "mid back" in canon:
                return "thoracic"
            if "shoulder" in canon:
                return "shoulder"
            if "knee" in canon:
                return "knee"
    except Exception:
        pass

    for label, pattern in _BODY_REGION_PATTERNS:
        if pattern.search(low):
            return label
    return "general"

