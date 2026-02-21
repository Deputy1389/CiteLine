"""
Deterministic text quality gates to suppress synthetic or garbage output.
"""
from __future__ import annotations

import re
import math
from typing import Iterable

_MEDICAL_TERMS = {
    "pain","injury","imaging","mri","xray","ct","ultrasound","procedure","surgery",
    "diagnosis","assessment","impression","treatment","therapy","pt","physical",
    "discharge","admission","ed","emergency","hospital","clinic","visit","follow",
    "medication","mg","injection","epidural","radiculopathy","strain","sprain",
    "lumbar","cervical","thoracic","spine","disc","herniation","fracture",
    "mm","cm","left","right","bilateral","worsened","improved","report","denies",
    "presented","complaint","history","hpi","plan","vitals","blood","pressure",
}
_STOPWORDS = {
    "the","and","or","of","to","in","for","with","on","at","by","from","as","an","a","is","was","were","be","been","are",
    "this","that","these","those","it","its","their","his","her","he","she","they","we","you","i","but","not","no","yes",
}

_FAX_ARTIFACT_RE = re.compile(
    r"^(from|to|fax|page|date|time)\s*[:#]|^\s*\d{3}[-\s]?\d{3}[-\s]?\d{4}\s*$",
    re.IGNORECASE,
)
_REPEATED_LABEL_RE = re.compile(r"(pain assessment:?\s*){2,}", re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[^A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"\s+", text.strip()) if t]


def _medical_density(tokens: Iterable[str]) -> float:
    toks = [t.lower() for t in tokens]
    if not toks:
        return 0.0
    hits = sum(1 for t in toks if t in _MEDICAL_TERMS or re.search(r"\d", t))
    return hits / max(1, len(toks))


def _diversity_score(text: str) -> float:
    cleaned = _NON_WORD_RE.sub("", text.lower())
    if not cleaned:
        return 0.0
    unique = len(set(cleaned))
    return unique / max(1, len(cleaned))


def clean_text(text: str) -> str:
    if not text:
        return ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    cleaned_lines: list[str] = []
    seen = set()
    for line in lines:
        if _FAX_ARTIFACT_RE.search(line):
            continue
        line = _REPEATED_LABEL_RE.sub("Pain Assessment: ", line)
        line = re.sub(r"\s{2,}", " ", line).strip()
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_lines.append(line)
    return " ".join(cleaned_lines).strip()


def quality_score(text: str) -> float:
    if not text:
        return 0.0
    tokens = _tokenize(text)
    if len(tokens) < 4:
        return 0.0
    med_density = _medical_density(tokens)
    diversity = _diversity_score(text)
    length_score = min(1.0, math.log1p(len(text)) / 6.0)
    return max(0.0, min(1.0, 0.45 * med_density + 0.35 * diversity + 0.2 * length_score))


def explain_flags(text: str) -> list[str]:
    flags = []
    if not text or len(text.strip()) < 20:
        flags.append("too_short")
    if _FAX_ARTIFACT_RE.search(text):
        flags.append("fax_artifact")
    if _REPEATED_LABEL_RE.search(text):
        flags.append("repeated_labels")
    if _diversity_score(text) < 0.15:
        flags.append("low_diversity")
    if _medical_density(_tokenize(text)) < 0.08:
        flags.append("low_medical_density")
    return flags


def is_garbage(text: str) -> bool:
    if not text:
        return True
    cleaned = clean_text(text)
    if not cleaned:
        return True
    tokens = _tokenize(cleaned)
    med_density = _medical_density(tokens)
    stopword_ratio = sum(1 for t in tokens if t.lower() in _STOPWORDS) / max(1, len(tokens))
    if med_density < 0.05 and stopword_ratio > 0.35:
        return True
    if quality_score(cleaned) < 0.28:
        return True
    return False
