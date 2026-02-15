"""
Step 9 — De-duplication + merge.
Merge Events with same (provider_id, event_type, date) when pages contiguous or citations overlap.
Cap facts at 10.
"""
from __future__ import annotations

from packages.shared.models import Event, Warning


def _events_match(a: Event, b: Event) -> bool:
    """Check if two events should be merged."""
    if a.provider_id != b.provider_id:
        return False
    if a.event_type != b.event_type:
        return False
    if a.date.sort_date() != b.date.sort_date():
        return False
    # Check page overlap or contiguity
    pages_a = set(a.source_page_numbers)
    pages_b = set(b.source_page_numbers)
    if pages_a & pages_b:
        return True
    # Contiguous if max(a) + 1 == min(b) or vice versa
    if max(pages_a) + 1 >= min(pages_b) or max(pages_b) + 1 >= min(pages_a):
        return True
    return False


def _merge_events(a: Event, b: Event) -> Event:
    """Merge event b into event a."""
    # Combine facts (dedup by text, cap at 10)
    seen_texts = {f.text for f in a.facts}
    for fact in b.facts:
        if fact.text not in seen_texts and len(a.facts) < 10:
            a.facts.append(fact)
            seen_texts.add(fact.text)

    # Combine citation_ids
    existing_ids = set(a.citation_ids)
    for cid in b.citation_ids:
        if cid not in existing_ids:
            a.citation_ids.append(cid)

    # Combine source pages
    existing_pages = set(a.source_page_numbers)
    for p in b.source_page_numbers:
        if p not in existing_pages:
            a.source_page_numbers.append(p)

    # Combine diagnoses, procedures
    a.diagnoses.extend(b.diagnoses)
    a.procedures.extend(b.procedures)

    # Keep higher confidence
    a.confidence = max(a.confidence, b.confidence)

    return a


def deduplicate_events(events: list[Event]) -> tuple[list[Event], list[Warning]]:
    """
    Deduplicate and merge events.
    Returns (merged_events, warnings).
    """
    warnings: list[Warning] = []
    if not events:
        return events, warnings

    merged: list[Event] = [events[0]]

    for event in events[1:]:
        was_merged = False
        for i, existing in enumerate(merged):
            if _events_match(existing, event):
                merged[i] = _merge_events(existing, event)
                was_merged = True
                break
        if not was_merged:
            merged.append(event)

    # Final cap on facts
    for event in merged:
        if len(event.facts) > 10:
            event.facts = event.facts[:10]

    return merged, warnings
