from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ConceptHit:
    domain: str
    canonical: str
    source: str
    confidence: float


_INJURY_RULES: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"\bcervical radiculopathy\b", re.IGNORECASE), "cervical radiculopathy", 0.95),
    (re.compile(r"\blumbar radiculopathy\b", re.IGNORECASE), "lumbar radiculopathy", 0.95),
    (re.compile(r"\bdisc protrusion\b", re.IGNORECASE), "disc protrusion", 0.9),
    (re.compile(r"\bdisc herniation\b", re.IGNORECASE), "disc herniation", 0.9),
    (re.compile(r"\bforaminal narrowing\b", re.IGNORECASE), "foraminal narrowing", 0.85),
    (re.compile(r"\bfracture\b", re.IGNORECASE), "fracture", 0.9),
    (re.compile(r"\bstrain\b", re.IGNORECASE), "strain", 0.8),
    (re.compile(r"\bsprain\b", re.IGNORECASE), "sprain", 0.8),
    (re.compile(r"\bwound infection\b", re.IGNORECASE), "wound infection", 0.9),
    (re.compile(r"\binfection\b", re.IGNORECASE), "infection", 0.8),
    (re.compile(r"\bneck(?:\s*,)?\s+and\s+low\s+back\s+pain\b", re.IGNORECASE), "neck pain", 0.8),
    (re.compile(r"\bneck pain\b", re.IGNORECASE), "neck pain", 0.75),
    (re.compile(r"\blow back pain\b", re.IGNORECASE), "low back pain", 0.75),
    (re.compile(r"\bback pain\b", re.IGNORECASE), "back pain", 0.7),
]

_PROCEDURE_RULES: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"\bepidural steroid injection\b|\besi\b", re.IGNORECASE), "epidural steroid injection", 0.95),
    (re.compile(r"\binterlaminar\b", re.IGNORECASE), "interlaminar injection", 0.9),
    (re.compile(r"\btransforaminal\b", re.IGNORECASE), "transforaminal injection", 0.9),
    (re.compile(r"\bfluoroscopy\b", re.IGNORECASE), "fluoroscopy-guided procedure", 0.85),
    (re.compile(r"\bdepo-?medrol\b", re.IGNORECASE), "depo-medrol administered", 0.85),
    (re.compile(r"\blidocaine\b", re.IGNORECASE), "lidocaine administered", 0.85),
]

_IMAGING_RULES: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"\bmri\b", re.IGNORECASE), "mri", 0.9),
    (re.compile(r"\bx-?ray\b|\bxr\b", re.IGNORECASE), "x-ray", 0.85),
    (re.compile(r"\bct\b|\bcta\b", re.IGNORECASE), "ct", 0.85),
    (re.compile(r"\bimpression\b", re.IGNORECASE), "impression", 0.8),
]

_DISPOSITION_RULES: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"\bdischarged home\b|\bhome with\b", re.IGNORECASE), "Home", 0.95),
    (re.compile(r"\bskilled nursing\b|\bsnf\b", re.IGNORECASE), "SNF", 0.95),
    (re.compile(r"\bhospice\b", re.IGNORECASE), "Hospice", 0.95),
    (re.compile(r"\brehab(?:ilitation)?\b", re.IGNORECASE), "Rehab", 0.9),
    (re.compile(r"\btransfer(?:red)?\b", re.IGNORECASE), "Transfer", 0.85),
    (re.compile(r"\bama\b|against medical advice", re.IGNORECASE), "AMA", 0.9),
    (re.compile(r"\bdeceased\b|\bdeath\b|\bexpired\b", re.IGNORECASE), "Death", 0.95),
]


def extract_concepts(text: str) -> list[ConceptHit]:
    src = text or ""
    out: list[ConceptHit] = []
    for rex, label, conf in _INJURY_RULES:
        if rex.search(src):
            out.append(ConceptHit("injury", label, src, conf))
    for rex, label, conf in _PROCEDURE_RULES:
        if rex.search(src):
            out.append(ConceptHit("procedure", label, src, conf))
    for rex, label, conf in _IMAGING_RULES:
        if rex.search(src):
            out.append(ConceptHit("imaging", label, src, conf))
    for rex, label, conf in _DISPOSITION_RULES:
        if rex.search(src):
            out.append(ConceptHit("disposition", label, src, conf))
    return out


def canonical_injuries(facts: list[str]) -> list[str]:
    hits: set[str] = set()
    for fact in facts or []:
        for c in extract_concepts(fact):
            if c.domain == "injury":
                hits.add(c.canonical)
    return sorted(hits)


def canonical_procedures(facts: list[str]) -> list[str]:
    hits: set[str] = set()
    for fact in facts or []:
        for c in extract_concepts(fact):
            if c.domain == "procedure":
                hits.add(c.canonical)
    return sorted(hits)


def canonical_disposition(facts: list[str]) -> str | None:
    ranked: list[tuple[float, str]] = []
    for fact in facts or []:
        for c in extract_concepts(fact):
            if c.domain == "disposition":
                ranked.append((c.confidence, c.canonical))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][1]
