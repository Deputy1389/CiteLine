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

def append_to_event(event: Event, text: str, page: Page, citations: list[Citation], author_name=None, author_role=None):
    """Append a clinical line to an existing event fact list."""
    cit = _make_citation(page, text)
    citations.append(cit)
    
    # Update encounter type if new text is stronger
    new_etype = detect_encounter_type(text)
    if PRIORITY_MAP.get(new_etype, 0) > PRIORITY_MAP.get(event.event_type, 0):
        event.event_type = new_etype

    # Update author if provided and currently unknown
    if author_name and not event.author_name:
        event.author_name = author_name
        event.author_role = author_role

    # Check if this line contains new indicators
    fact_text = text
    for pattern, label in CLINICAL_INDICATORS:
        if re.search(pattern, text):
            if label not in text:
                fact_text = f"{label}: {text}"
            break

    event.facts.append(_make_fact(fact_text, FactKind.OTHER, cit.citation_id))
    event.citation_ids.append(cit.citation_id)
