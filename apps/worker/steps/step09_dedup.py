"""
Step 9 — Signal Filtering + Event Consolidation.
Merge adjacent events with same (date, time, provider, event_type).
Drop events that fail the clinical signal test.
"""
from __future__ import annotations
from collections import defaultdict

from packages.shared.models import Event, Warning
from apps.worker.steps.events.signal_filter import is_clinical_signal_event


def _get_event_key(e: Event) -> tuple:
    """Deterministic grouping key."""
    if not e.date:
        return (None, None, e.provider_id, e.event_type)
    
    ext = e.date.extensions or {}
    time_val = ext.get("time")
    
    # Sort date
    sd = e.date.sort_date()
    
    return (sd, time_val, e.provider_id, e.event_type)


def _merge_events(a: Event, b: Event) -> Event:
    """Merge event b into event a."""
    if not a.extensions: a.extensions = {}
    if "merged_from" not in a.extensions:
        a.extensions["merged_from"] = [a.event_id]
    a.extensions["merged_from"].append(b.event_id)

    # Combine facts (dedup by text, cap at 30)
    seen_texts = {f.text for f in a.facts}
    for fact in b.facts:
        if fact.text not in seen_texts and len(a.facts) < 30:
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

    # Combine other fields
    a.diagnoses.extend(b.diagnoses)
    a.medications.extend(b.medications)
    a.procedures.extend(b.procedures)

    # Keep highest confidence
    a.confidence = max(a.confidence, b.confidence)

    return a


def deduplicate_events(events: list[Event]) -> tuple[list[Event], list[Warning]]:
    """
    Consolidate events by timestamp and filter for clinical signal.
    """
    warnings: list[Warning] = []
    if not events:
        return events, warnings

    # 1. Sort all events by date/time sort_key to bring identical timestamps together
    events.sort(key=lambda e: e.date.sort_key() if e.date else (99, "UNKNOWN"))

    # 2. Merge events with same (date, time)
    # Different encounter types at same time are merged; highest priority type wins.
    from apps.worker.steps.events.clinical import PRIORITY_MAP
    
    def _get_time_key(e: Event):
        if not e.date: return (None, None, None)
        ext = e.date.extensions or {}
        return (e.date.sort_date(), ext.get("time"))

    merged: list[Event] = []
    if not events:
        return [], warnings

    current_event = events[0]
    
    for i in range(1, len(events)):
        next_event = events[i]
        
        if _get_time_key(current_event) == _get_time_key(next_event):
            # Update encounter type if next one is higher priority
            if PRIORITY_MAP.get(next_event.event_type, 0) > PRIORITY_MAP.get(current_event.event_type, 0):
                current_event.event_type = next_event.event_type
            current_event = _merge_events(current_event, next_event)
        else:
            merged.append(current_event)
            current_event = next_event
            
    merged.append(current_event)

    # 3. Filter individual facts and the events themselves
    from apps.worker.steps.events.signal_filter import BOILERPLATE_PATTERNS, LEGEND_PATTERNS
    import re

    final_events = []
    for e in merged:
        # Filter out boilerplate facts from this event
        filtered_facts = []
        for fact in e.facts:
            text = fact.text.strip()
            is_bp = any(re.search(p, text) for p in BOILERPLATE_PATTERNS)
            is_leg = any(re.search(p, text.lower()) for p in LEGEND_PATTERNS)
            
            # Rule: Drop if shorter than 15 and no numeric signal
            from apps.worker.steps.events.signal_filter import NUMERIC_SIGNALS
            has_num = any(re.search(p, text.lower()) for p in NUMERIC_SIGNALS)
            is_short = len(text) < 15 and not has_num
            
            if not (is_bp or is_leg or is_short):
                filtered_facts.append(fact)
        
        e.facts = filtered_facts
        
        # Check if event still has signal
        if is_clinical_signal_event(e):
            final_events.append(e)

    return final_events, warnings
