import uuid
import re
from typing import Optional
from packages.shared.models import Event, EventType, Fact, FactKind, EventDate
from apps.worker.steps.events.legal_quality import clean_and_validate_facts, extract_author

def improve_legal_usability(events: list[Event]) -> list[Event]:
    """
    Apply legal-grade post-processing to consolidate, split, and filter events
    for attorney-level review.
    """
    if not events:
        return events

    # Step 1: Historical Reference Isolation
    processed_events = []
    for event in events:
        original_facts = list(event.facts)
        # Pre-clean facts (merges wrapped, stitches quotes, removes junk)
        event.facts = clean_and_validate_facts(event.facts)
        if not event.facts and original_facts:
            # Preserve event cardinality; keep original facts and mark for review.
            event.facts = original_facts
            if "NEEDS_REVIEW" not in event.flags:
                event.flags.append("NEEDS_REVIEW")
            if "LEGAL_USABILITY_FACT_CLEAN_EMPTY" not in event.flags:
                event.flags.append("LEGAL_USABILITY_FACT_CLEAN_EMPTY")

        clean_facts = []
        ref_facts = []
        
        event_month = event.date.partial_month if event.date else None
        event_day = event.date.partial_day if event.date else None
        
        for fact in event.facts:
            text = fact.text
            is_ref = False
            
            # Pattern check for dates (MM/DD or MM-DD)
            # Exclude pain scores like 9/10
            date_match = re.search(r"\b(\d{1,2})/(\d{1,2})\b", text)
            if date_match:
                m, d = int(date_match.group(1)), int(date_match.group(2))
                is_pain = d == 10 and re.search(r"pain|score|level", text.lower())
                if not is_pain and (m != event_month or d != event_day):
                    is_ref = True
            
            # Keywords check
            if any(kw in text.lower() for kw in ["history of", "four-year history", "prior to", "previously"]):
                is_ref = True
                
            if is_ref:
                ref_facts.append(fact)
            else:
                clean_facts.append(fact)
        
        # If we have references and still have primary facts, split them out.
        # Never let reference isolation eliminate the original event.
        if ref_facts and clean_facts:
            ref_event = Event(
                event_id=uuid.uuid4().hex[:16],
                provider_id=event.provider_id,
                event_type=EventType.REFERENCED_PRIOR_EVENT,
                date=event.date,
                facts=ref_facts,
                confidence=50,
                flags=["is_reference"],
                citation_ids=[],
                source_page_numbers=event.source_page_numbers,
                extensions={**(event.extensions or {}), "derived_from_event_id": event.event_id}
            )
            # Union citation_ids from constituents
            all_cids = []
            for f in ref_facts:
                all_cids.extend(f.citation_ids)
                if f.citation_id: all_cids.append(f.citation_id)
            ref_event.citation_ids = list(set(all_cids))
            processed_events.append(ref_event)
        elif ref_facts and not clean_facts:
            clean_facts = list(event.facts)
            if "NEEDS_REVIEW" not in event.flags:
                event.flags.append("NEEDS_REVIEW")
            if "LEGAL_USABILITY_REFERENCE_ONLY" not in event.flags:
                event.flags.append("LEGAL_USABILITY_REFERENCE_ONLY")
            
        # Update current event facts
        event.facts = clean_facts
        # Re-extract author from cleaned facts if not set or if new signature found
        _update_author_from_facts(event)
        
        if event.facts or event.event_type in [EventType.HOSPITAL_ADMISSION, EventType.HOSPITAL_DISCHARGE]:
            processed_events.append(event)

    # Step 2: Split "Fat" Admission events
    final_events = []
    for event in processed_events:
        total_chars = sum(len(f.text) for f in event.facts)
        if event.event_type == EventType.HOSPITAL_ADMISSION and (len(event.facts) > 6 or total_chars > 400):
            # Split logic
            summary_facts = []
            orders_facts = []
            social_facts = []
            
            # Category priority: Caregiver Strain > Orders & Meds > Admission Summary
            for f in event.facts:
                t = f.text.lower()
                # Social/Strain keywords (Highest Priority)
                social_kws = ["partner", "caregiver", "manage", "cope", "expressed concerns", "bathroom", "strain", "toilet", "diarrhea", "vomit", "emesis"]
                # Meds/Orders keywords
                orders_kws = ["mg", "ml", "every", "prn", "diet", "dose", "order", "administered", "medicated", "oxycodone", "phenergan", "ibuprofen", "supplement", "vitamin"]

                if any(kw in t for kw in social_kws) or '"' in t or "“" in t:
                    social_facts.append(f)
                elif any(kw in t for kw in orders_kws):
                    orders_facts.append(f)
                else:
                    summary_facts.append(f)
            
            # Create sub-events
            if summary_facts:
                final_events.append(_derive_event(event, summary_facts, "Admission Summary"))
            if orders_facts:
                final_events.append(_derive_event(event, orders_facts, "Orders & Meds"))
            if social_facts:
                final_events.append(_derive_event(event, social_facts, "Caregiver Strain"))
        else:
            final_events.append(event)

    # Preserve events from input; no implicit count reduction at normalization stage.
    return final_events

def _update_author_from_facts(event: Event):
    """Scan facts for signatures and update author info."""
    authors = []
    for f in event.facts:
        name, role = extract_author(f.text)
        if name:
            authors.append((name, role))
    
    if authors:
        unique_authors = list(set(authors))
        if len(unique_authors) > 1:
            event.author_name = "Multiple"
            event.author_role = None
            event.extensions["authors"] = [{"name": a[0], "role": a[1]} for a in unique_authors]
        else:
            event.author_name = unique_authors[0][0]
            event.author_role = unique_authors[0][1]
    elif not event.author_name:
        event.author_name = "Unknown"

def _derive_event(original: Event, facts: list[Fact], section_name: str) -> Event:
    new_evt = Event(
        event_id=uuid.uuid4().hex[:16],
        provider_id=original.provider_id,
        event_type=original.event_type,
        date=original.date,
        author_name=original.author_name,
        author_role=original.author_role,
        facts=facts,
        confidence=original.confidence,
        flags=original.flags,
        source_page_numbers=original.source_page_numbers,
        extensions={
            **(original.extensions or {}),
            "derived_from_event_id": original.event_id,
            "legal_section": section_name
        }
    )
    # Point Citations: union of constituent facts
    all_cids = []
    for f in facts:
        all_cids.extend(f.citation_ids)
        if f.citation_id: all_cids.append(f.citation_id)
    new_evt.citation_ids = list(set(all_cids))
    
    # Update author for this specific derived event if facts contain a signature
    _update_author_from_facts(new_evt)
    
    return new_evt
