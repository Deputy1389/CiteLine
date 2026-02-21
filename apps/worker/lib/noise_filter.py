from __future__ import annotations

import re


MEDICAL_TERMS = {
    "diagnosis", "impression", "assessment", "plan", "procedure", "surgery", "injection", "fluoroscopy",
    "lidocaine", "depo-medrol", "pain", "fracture", "radiculopathy", "protrusion", "herniation", "stenosis",
    "infection", "wound", "discharge", "admission", "ed", "emergency", "mri", "ct", "x-ray", "therapy",
    "medication", "mg", "tablet", "capsule", "hospital", "clinic", "follow-up",
}
STOPWORDS = {
    "the", "and", "of", "to", "in", "for", "on", "with", "a", "an", "is", "are", "was", "were", "this", "that",
    "at", "as", "it", "or", "by", "from", "be", "been", "if", "into", "about",
}
ICD_RE = re.compile(r"\b([A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?)\b", re.IGNORECASE)
CPT_RE = re.compile(r"\b\d{5}\b")
DOSAGE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(mg|ml|mcg|g)\b", re.IGNORECASE)
HEADING_RE = re.compile(r"\b(impression|assessment|plan|diagnosis|clinical impression|chief complaint|procedure)\b", re.IGNORECASE)


def medical_token_density(text: str) -> float:
    tokens = re.findall(r"[a-z0-9\-]+", (text or "").lower())
    if not tokens:
        return 0.0
    medical_hits = sum(1 for t in tokens if t in MEDICAL_TERMS)
    return medical_hits / max(1, len(tokens))


def has_structured_signals(text: str) -> bool:
    t = text or ""
    low = t.lower()
    return bool(ICD_RE.search(t) or CPT_RE.search(t) or DOSAGE_RE.search(low) or HEADING_RE.search(low))


def is_noise_span(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    low = t.lower()
    if re.search(r"\b(lorem ipsum|qwerty|asdf|difficult mission late kind|product main couple design)\b", low):
        return True
    med_density = medical_token_density(t)
    structured = has_structured_signals(t)
    tokens = re.findall(r"[a-z]+", low)
    stop_ratio = (sum(1 for tok in tokens if tok in STOPWORDS) / max(1, len(tokens))) if tokens else 1.0
    return (med_density < 0.08) and (not structured) and (stop_ratio > 0.55)

