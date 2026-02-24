"""
Step 9 - Signal Filtering + Event Consolidation.
Merge adjacent events with same (date, time, provider, event_type).
Also collapse events that share source pages (same physical page = same encounter).
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

    # Combine facts (dedup by text, cap at 10 to keep merged rows concise/useful)
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

    # 2. Merge events with same (date, time, provider, event_type)
    # Keep encounter types separate to avoid collapsing distinct same-day events.
    from apps.worker.steps.events.clinical import PRIORITY_MAP

    merged: list[Event] = []
    if not events:
        return [], warnings

    current_event = events[0]
    
    for i in range(1, len(events)):
        next_event = events[i]
        
        if _get_event_key(current_event) == _get_event_key(next_event):
            # Update encounter type if next one is higher priority
            if PRIORITY_MAP.get(next_event.event_type, 0) > PRIORITY_MAP.get(current_event.event_type, 0):
                current_event.event_type = next_event.event_type
            current_event = _merge_events(current_event, next_event)
        else:
            merged.append(current_event)
            current_event = next_event
            
    merged.append(current_event)

    # 2b. Second pass: collapse events that share source pages.
    # One physical page should produce at most one event per (date, provider).
    # This handles cases where the same page spawns multiple events with different timestamps
    # or slightly different event type classifications (e.g. CLINICAL_NOTE vs PT_VISIT).
    from packages.shared.models import EventType as _ET
    
    # Define "soft" types that can be merged if they appear on the same page
    SOFT_TYPES = {_ET.PT_VISIT, _ET.OFFICE_VISIT, _ET.INPATIENT_DAILY_NOTE}

    page_groups: dict[tuple, list[Event]] = defaultdict(list)
    for evt in merged:
        sd = evt.date.sort_date() if evt.date else None
        # Use a "type group" instead of strict event_type for soft types
        type_key = "SOFT_CLINICAL" if evt.event_type in SOFT_TYPES else evt.event_type
        key = (sd, evt.provider_id, type_key)
        page_groups[key].append(evt)

    collapsed: list[Event] = []
    for key, group_evts in page_groups.items():
        if len(group_evts) == 1:
            collapsed.append(group_evts[0])
            continue

        # Union-find: merge events that share at least one source page
        n = len(group_evts)
        parent = list(range(n))

        def _find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        page_sets = [set(e.source_page_numbers) for e in group_evts]
        for i in range(n):
            for j in range(i + 1, n):
                if page_sets[i] & page_sets[j]:
                    pi, pj = _find(i), _find(j)
                    if pi != pj:
                        parent[pi] = pj

        components: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            components[_find(i)].append(i)

        for indices in components.values():
            base = group_evts[indices[0]]
            for idx in indices[1:]:
                base = _merge_events(base, group_evts[idx])
            collapsed.append(base)

    merged = collapsed

    # 2c. Third pass: merge same-day same-type events if providers match or one is unknown.
    # This handles documentation fragmentation across multiple pages on the same encounter day.
    day_groups: dict[tuple, list[Event]] = defaultdict(list)
    for evt in merged:
        sd = evt.date.sort_date() if evt.date else None
        # Use SOFT_CLINICAL group for mergeable types
        type_key = "SOFT_CLINICAL" if evt.event_type in SOFT_TYPES else evt.event_type
        key = (sd, type_key)
        day_groups[key].append(evt)

    final_merged: list[Event] = []
    for key, group_evts in day_groups.items():
        if len(group_evts) == 1:
            final_merged.append(group_evts[0])
            continue

        # Group within the day by provider compatibility
        # If two events have different SPECIFIC providers, don't merge.
        # If one has "unknown", merge into the specific one.
        # If both are "unknown", merge.
        n = len(group_evts)
        parent = list(range(n))

        def _find_final(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            for j in range(i + 1, n):
                p1 = group_evts[i].provider_id or "unknown"
                p2 = group_evts[j].provider_id or "unknown"
                
                match = (p1 == p2) or (p1 == "unknown") or (p2 == "unknown")
                if match:
                    # Further check: don't merge if they have different explicit times
                    t1 = (group_evts[i].date.extensions or {}).get("time") if group_evts[i].date else None
                    t2 = (group_evts[j].date.extensions or {}).get("time") if group_evts[j].date else None
                    if t1 and t2 and t1 != t2:
                        continue # Keep distinct timestamped encounters separate
                        
                    pi, pj = _find_final(i), _find_final(j)
                    if pi != pj:
                        parent[pi] = pj

        components: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            components[_find_final(i)].append(i)

        for indices in components.values():
            base = group_evts[indices[0]]
            for idx in indices[1:]:
                other = group_evts[idx]
                # If base has unknown provider, adopt other's provider
                if (base.provider_id == "unknown" or not base.provider_id) and other.provider_id != "unknown":
                    base.provider_id = other.provider_id
                base = _merge_events(base, other)
            final_merged.append(base)

    merged = final_merged

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
