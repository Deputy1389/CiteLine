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
    # PT / Rehab / Physical Exam terms
    "stable","tolerated","tolerating","palpation","movement","rom","strength","gait",
    "musculature","paraspinal","tenderness","extension","flexion","sensation","intact",
    "reflexes","motor","sensory","vertebral","alignment","lordosis","scoliosis",
    "spasm","trigger","points","manipulation","adjustment","exercise","activities",
    "functional","ambulation","mobility","balance","transfer","weight","bearing",
    "extremity","bilateral","distal","proximal","superior","inferior","lateral","medial",
}
_STOPWORDS = {
    "the","and","or","of","to","in","for","with","on","at","by","from","as","an","a","is","was","were","be","been","are",
    "this","that","these","those","it","its","their","his","her","he","she","they","we","you","i","but","not","no","yes",
}

_FAX_ARTIFACT_RE = re.compile(
    r"^(from|to|fax|page|date|time|sent)\s*[:#]"
    r"|^fax\s*id\s*[:#]"
    r"|^\s*\d{3}[-\s]?\d{3}[-\s]?\d{4}\s*$"
    r"|\bto\s*:\s*records?\s*(?:dept|department)\b"
    r"|\bpage\s*:\s*0*\d+\s*$"
    r"|\brecords\s*dept\b"
    r"|^\s*from\s*:\s*\(?\d{3}\)?\s*\d{3}-\d{4}\s*$"
    r"|^\s*page\s*:\s*\d{3}\s*$",
    re.IGNORECASE,
)
# Date-prefixed fax routing lines: "10/11/2024 12:01 FROM: ..."
_FAX_DATE_FROM_RE = re.compile(
    r"^\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s+(?:FROM|TO)\s*:",
    re.IGNORECASE,
)
# Inline fax footer: timestamps, phone numbers, and page markers that appear mid-text after line joining
_FAX_INLINE_RE = re.compile(
    r"\s*\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s+\(?\d{3}\)?[-\s]\d{3}[-\s]\d{4}\s+P\.\d+\.?"
    r"|\s*\(?\d{3}\)?[-\s]\d{3}[-\s]\d{4}\s+P\.\d+\.?"
    r"|\s*Fax\s*ID\s*:\s*\d+\s*"
    r"|\s*Page\s*:\s*\d+\s*",
    re.IGNORECASE,
)
_REPEATED_LABEL_RE = re.compile(r"(pain assessment:?\s*){2,}", re.IGNORECASE)
_NON_WORD_RE = re.compile(r"[^A-Za-z0-9]+")
_CID_ARTIFACT_RE = re.compile(r"\(cid:\d+\)", re.IGNORECASE)

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
        line = _CID_ARTIFACT_RE.sub("", line).strip()
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


_TIMESTAMP_PREFIX_RE = re.compile(
    r"^\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+\d{3,4}\s+"  # "10/11 1820 " or "10/11/2024 1820 "
    r"|^\s*\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?\s+"  # "2024-10-11 18:20 "
    r"|^\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+\d{1,2}:\d{2}\s+",  # "10/11 18:20 "
)


def should_quarantine_fact(text: str) -> bool:
    """
    Clause VI — OCR Quarantine gate for individual Fact text.

    A fact is quarantined if it contains ZERO medical signal (no medical terms,
    no digits) in its body text after stripping EMR label prefixes and any
    leading flowsheet timestamp (e.g. "10/11 1820 ").

    Only applied to facts under 80 characters — longer facts have enough context
    that a false positive would do more harm than good.

    Returns True if the fact should be marked technical_noise=True.
    Facts are never deleted; callers must set fact.technical_noise = True and
    suppress from attorney-facing output while retaining for audit.
    """
    if not text or len(text.strip()) < 4:
        return False

    # Strip leading EMR flowsheet timestamp before label/body analysis
    stripped = _TIMESTAMP_PREFIX_RE.sub("", text).strip()
    
    # Recursive multi-label strip
    body = stripped
    while True:
        next_body = _EMR_LABEL_PREFIX_RE.sub("", body).strip()
        if next_body == body:
            break
        body = next_body
        
    analyze = body if body else stripped

    # Only quarantine short facts — long facts have inherent context complexity
    if len(analyze) >= 80:
        return False

    tokens = _tokenize(analyze)
    if not tokens:
        return False

    # Require at least one medical-domain token (term or digit-containing value)
    has_medical_signal = any(
        t.lower().rstrip(".,;:!?()[]") in _MEDICAL_TERMS or re.search(r"\d", t)
        for t in tokens
    )
    return not has_medical_signal


def is_garbage(text: str) -> bool:
    if not text:
        return True
    
    # If it's a multi-line block, check if a significant portion of it is garbage
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) > 2:
        garbage_lines = 0
        for line in lines:
            if _is_line_garbage(line):
                garbage_lines += 1
        # If more than 40% of lines are garbage, the whole block is suspicious
        if garbage_lines / len(lines) > 0.4:
            return True

    cleaned = clean_text(text)
    if not cleaned:
        return True
    return _is_line_garbage(cleaned)


def _is_line_garbage(line: str) -> bool:
    if not line:
        return True
    if _FAX_ARTIFACT_RE.search(line):
        return True

    # Multi-label strip: recursively remove all EMR prefixes anywhere in the line
    # to find the TRUE clinical body.
    analyze = line
    while True:
        stripped = _EMR_LABEL_PREFIX_RE.sub("", analyze).strip()
        if stripped == analyze:
            break
        analyze = stripped
    
    # Also strip common medical labels that appear mid-line
    mid_label_pattern = r"(?i)\b(?:pain|vitals|pt|meds|orders|rounding)\s*(?:assessment|level|scale|check|signs|request|given|received)?\s*:?\s*"
    analyze = re.sub(mid_label_pattern, " ", analyze).strip()

    tokens = _tokenize(analyze)
    if len(tokens) < 3:
        if not tokens:
            return True
        has_digits = any(re.search(r"\d", t) for t in tokens)
        has_medical_word = any(t.lower().rstrip(".,;:!?()[]") in _MEDICAL_TERMS for t in tokens)
        if has_digits or has_medical_word:
            return False
        return True
    
    med_density = _medical_density(tokens)
    diversity = _diversity_score(analyze)

    # Aggressive rejection for short noisy strings (e.g. "Late its part cost")
    if len(analyze) < 40 and med_density < 0.05 and diversity < 0.15:
        return True

    # Consecutive non-medical word runs (hallmark of word salad).
    consecutive_nonmed = 0
    max_consecutive = 0
    for t in tokens:
        low = t.lower().rstrip(".,;:!?()[]")
        # Treat assessment/plan/note as medical terms to prevent false positives on valid headers,
        # but the BODY needs actual medical signal.
        if low in _MEDICAL_TERMS or re.search(r"\d", t):
            consecutive_nonmed = 0
        else:
            consecutive_nonmed += 1
            max_consecutive = max(max_consecutive, consecutive_nonmed)

    # Tighten max allowed: 3+ non-medical tokens in a row is highly suspicious
    # for small strings.
    max_allowed = 2 if len(tokens) <= 6 else 4
    if max_consecutive > max_allowed:
        return True

    # For longer texts, require minimum medical density
    if len(line) > 50 and med_density < 0.08:
        return True
    return False
