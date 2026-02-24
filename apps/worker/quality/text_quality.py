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
    # Unambiguous clinical terms missing from original set
    "patient","patients","presents","presenting","symptoms","symptom","complaints",
    "mva","mvc","trauma","swelling","numbness","weakness","radiating","radicular",
    "tenderness","concussion","laceration","contusion","abrasion",
    # Transport/mechanism-of-injury terms (almost always medical in records context)
    "accident","vehicle","collision","pedestrian","occupant","transport",
}
_STOPWORDS = {
    "the","and","or","of","to","in","for","with","on","at","by","from","as","an","a","is","was","were","be","been","are",
    "this","that","these","those","it","its","their","his","her","he","she","they","we","you","i","but","not","no","yes",
}

_FAX_ARTIFACT_RE = re.compile(
    r"^(from|to|fax|page|date|time)\s*[:#]"
    r"|^fax\s*id\s*[:#]"
    r"|^\s*\d{3}[-\s]?\d{3}[-\s]?\d{4}\s*$"
    r"|\bto\s*:\s*records?\s*(?:dept|department)\b"
    r"|\bpage\s*:\s*0*\d+\s*$",
    re.IGNORECASE,
)
# Date-prefixed fax routing lines: "10/11/2024 12:01 FROM: ..."
_FAX_DATE_FROM_RE = re.compile(
    r"^\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s+FROM\s*:",
    re.IGNORECASE,
)
# Inline fax footer: timestamps, phone numbers, and page markers that appear mid-text after line joining
_FAX_INLINE_RE = re.compile(
    r"\s*\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s+\(?\d{3}\)?[-\s]\d{3}[-\s]\d{4}\s+P\.\d+\.?"
    r"|\s*\(?\d{3}\)?[-\s]\d{3}[-\s]\d{4}\s+P\.\d+\.?",  # standalone phone+page
    re.IGNORECASE,
)
_REPEATED_LABEL_RE = re.compile(r"(pain assessment:?\s*){2,}", re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[^A-Za-z0-9]+")

# EMR label prefixes that should be stripped before quality analysis
# e.g. "Pain Assessment: gibberish" → analyze "gibberish" only
_EMR_LABEL_PREFIX_RE = re.compile(
    r"^(?:pain\s*(?:assessment|level|scale)?|vitals?\s*(?:check|signs?)?|rounding|"
    r"pt\.?\s*request|meds?\s*(?:given|administered)?|orders?\s*(?:received)?|"
    r"chief\s*complaint|assessment|hpi|subjective|objective|plan|"
    r"physician(?:'s)?\s*orders?)\s*:?\s*",
    re.IGNORECASE,
)


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
        if _FAX_ARTIFACT_RE.search(line) or _FAX_DATE_FROM_RE.search(line):
            continue
        line = _REPEATED_LABEL_RE.sub("Pain Assessment: ", line)
        line = re.sub(r"\s{2,}", " ", line).strip()
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_lines.append(line)
    result = " ".join(cleaned_lines).strip()
    # Strip inline fax artifacts (phone+page stamps that survived line joining)
    result = _FAX_INLINE_RE.sub("", result).strip()
    return result


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


def should_quarantine_fact(text: str) -> bool:
    """
    Clause VI — OCR Quarantine gate for individual Fact text.

    Criteria (all deterministic, no model calls):
    - dictionary hit ratio  < 0.40  (fewer than 40% tokens are real English/medical words)
    - medical lexicon density < 0.05  (almost no medical signal)
    - alphabetic token ratio  < 0.50  (majority tokens non-alphabetic → OCR noise)

    Returns True if the fact should be marked technical_noise=True.
    Facts are never deleted; callers must set fact.technical_noise = True and
    suppress from attorney-facing output while retaining for audit.
    """
    if not text or len(text.strip()) < 4:
        return False  # Too short to score — let is_garbage handle blanks

    body = _EMR_LABEL_PREFIX_RE.sub("", text).strip()
    analyze = body if body else text
    tokens = _tokenize(analyze)
    if not tokens:
        return False

    # Alphabetic token ratio: exclude tokens that are purely digits / punctuation
    alpha_tokens = [t for t in tokens if re.search(r"[A-Za-z]", t)]
    alpha_ratio = len(alpha_tokens) / len(tokens)

    # Medical lexicon density (existing helper, counts digits too)
    med_density = _medical_density(tokens)

    # Dictionary hit ratio: any token that is a medical term, stopword, or contains digits
    dict_hits = sum(
        1 for t in tokens
        if t.lower().rstrip(".,;:!?()[]") in _MEDICAL_TERMS
        or t.lower().rstrip(".,;:!?()[]") in _STOPWORDS
        or re.search(r"\d", t)
    )
    dict_ratio = dict_hits / len(tokens)

    # Quarantine if all three metrics fail threshold
    if dict_ratio < 0.40 and med_density < 0.05 and alpha_ratio < 0.50:
        return True
    return False


def is_garbage(text: str) -> bool:
    if not text:
        return True
    cleaned = clean_text(text)
    if not cleaned:
        return True
    if _FAX_ARTIFACT_RE.search(cleaned):
        return True

    # Strip EMR label prefix for body analysis.
    # "Pain Assessment: Blue cost expert" → analyze "Blue cost expert" only.
    body = _EMR_LABEL_PREFIX_RE.sub("", cleaned).strip()
    analyze = body if body else cleaned

    tokens = _tokenize(analyze)
    if len(tokens) < 3:
        # Short body after label strip: only garbage if it has no medical signal.
        # "Pain 8/10" → body "8/10" has a digit → NOT garbage.
        # "Pain Assessment: " → empty body → garbage.
        if not tokens:
            return True
        has_digits = any(re.search(r"\d", t) for t in tokens)
        has_medical_word = any(t.lower().rstrip(".,;:!?()[]") in _MEDICAL_TERMS for t in tokens)
        if has_digits or has_medical_word:
            return False
        return True
    med_density = _medical_density(tokens)
    diversity = _diversity_score(analyze)

    # Short-text check (use original cleaned length)
    if len(cleaned) < 30 and med_density < 0.02 and diversity < 0.1:
        return True

    # Consecutive non-medical word runs (hallmark of word salad).
    # Adaptive threshold: short texts need fewer consecutive non-medical words to fail.
    consecutive_nonmed = 0
    max_consecutive = 0
    for t in tokens:
        low = t.lower().rstrip(".,;:!?()[]")
        if low in _MEDICAL_TERMS or low in _STOPWORDS or re.search(r"\d", t):
            consecutive_nonmed = 0
        else:
            consecutive_nonmed += 1
            max_consecutive = max(max_consecutive, consecutive_nonmed)

    # ≤5 tokens (short body after label strip): 3+ consecutive non-medical = garbage
    # 6+ tokens: 6+ consecutive = garbage (allows natural sentences like "Patient presents via private vehicle")
    max_allowed = 2 if len(tokens) <= 5 else 5
    if max_consecutive > max_allowed:
        return True

    # For longer texts, require minimum medical density
    if len(cleaned) > 50 and med_density < 0.08:
        return True
    return False
