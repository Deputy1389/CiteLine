from __future__ import annotations
import re
from packages.shared.models import (
    Citation,
    Event,
    Fact,
    FactKind,
    Page,
)
from apps.worker.steps.events.common import _make_citation, _make_fact
from apps.worker.steps.events.clinical_patterns import CLINICAL_INDICATORS
from apps.worker.steps.events.encounter_classifier import detect_encounter_type, PRIORITY_MAP
from apps.worker.quality.text_quality import clean_text, is_structured_medical_signal


_MECHANISM_RE = re.compile(r"\b(motor vehicle|mvc|mva|collision|rear[- ]end|crash|auto accident|car accident)\b", re.IGNORECASE)
_DENIAL_RE = re.compile(r"\b(denies?|no prior|without prior|prior complaints?)\b", re.IGNORECASE)
_PAIN_SCORE_RE = re.compile(r"\bpain(?:\s*(?:score|level|severity))?\s*[:=]?\s*(\d{1,2})\s*/\s*10\b", re.IGNORECASE)


def _is_ed_verbatim_line(event: Event, text: str) -> bool:
    low = (text or "").lower()
    event_type = str(getattr(getattr(event, "event_type", None), "value", getattr(event, "event_type", "")) or "").lower()
    looks_ed = event_type in {"er_visit", "hospital_admission", "hospital_discharge", "inpatient_daily_note"} or any(
        token in low for token in ("chief complaint", "history of present illness", "hpi", "emergency department", "emergency room", "triage")
    )
    if not looks_ed:
        return False
    return bool(_MECHANISM_RE.search(low) or _DENIAL_RE.search(low) or _PAIN_SCORE_RE.search(low))


def append_to_event(event: Event, text: str, page: Page, citations: list[Citation], author_name=None, author_role=None):
    """Append a clinical line to an existing event fact list."""
    cleaned_text = clean_text(text).strip() or text
    cit = _make_citation(page, cleaned_text)
    citations.append(cit)
    
    # Update encounter type if new text is stronger
    new_etype = detect_encounter_type(cleaned_text)
    if PRIORITY_MAP.get(new_etype, 0) > PRIORITY_MAP.get(event.event_type, 0):
        event.event_type = new_etype

    # Update author if provided and currently unknown
    if author_name and not event.author_name:
        event.author_name = author_name
        event.author_role = author_role

    # Check if this line contains new indicators
    fact_text = cleaned_text
    fact_kind = FactKind.LAB if is_structured_medical_signal(cleaned_text) else FactKind.OTHER
    for pattern, label in CLINICAL_INDICATORS:
        if re.search(pattern, cleaned_text):
            if label not in cleaned_text:
                fact_text = f"{label}: {cleaned_text}"
            break

    event.facts.append(_make_fact(fact_text, fact_kind, cit.citation_id, verbatim=_is_ed_verbatim_line(event, fact_text)))
    event.citation_ids.append(cit.citation_id)
