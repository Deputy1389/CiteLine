"""
Extract events from Operative Reports.
"""
from __future__ import annotations

import uuid
from datetime import date

from packages.shared.models import (
    Citation,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Page,
    PageType,
    Provider,
    SkippedEvent,
    Warning,
)
from .common import _make_citation, _make_fact, _find_section

def extract_operative_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str],
) -> tuple[list[Event], list[Citation], list[Warning], list[SkippedEvent]]:
    """
    Extract events from pages classified as OPERATIVE_REPORT.
    """
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []
    skipped: list[SkippedEvent] = []

    # Process pages identified as OPERATIVE_REPORT
    op_pages = [p for p in pages if p.page_type == PageType.OPERATIVE_REPORT]

    for page in op_pages:
        page_dates = dates.get(page.page_number, [])
        event_date = page_dates[0] if page_dates else None
        
        provider_id = page_provider_map.get(page.page_number, "unknown")
        
        facts: list[Fact] = []
        
        # Extract Pre/Post-Op Diagnosis
        for header in ["Preoperative Diagnosis", "Postoperative Diagnosis", "Diagnosis"]:
            section = _find_section(page.text, header)
            if section:
                cit = _make_citation(page, section)
                citations.append(cit)
                facts.append(_make_fact(section, FactKind.DIAGNOSIS, cit.citation_id))
                
        # Extract Procedure
        for header in ["Procedure Performed", "Operation", "Procedure"]:
            section = _find_section(page.text, header)
            if section:
                cit = _make_citation(page, section)
                citations.append(cit)
                facts.append(_make_fact(section, FactKind.PROCEDURE, cit.citation_id))
                break # Only one procedure section needed usually

        # Extract Surgeon / Anesthesia
        for header in ["Surgeon", "Anesthesiologist", "Anesthesia"]:
            section = _find_section(page.text, header)
            if section:
                # Likely just a name or type
                summary = f"{header}: {section[:100].strip()}"
                cit = _make_citation(page, summary)
                citations.append(cit)
                facts.append(_make_fact(summary, FactKind.PROVIDER, cit.citation_id))

        if not facts and not event_date:
            skipped.append(SkippedEvent(
                page_numbers=[page.page_number],
                reason_code="NO_FACTS_OR_DATE",
                snippet=page.text[:100]
            ))
            continue

        # Create event
        events.append(Event(
            event_id=uuid.uuid4().hex,
            provider_id=provider_id,
            event_type=EventType.PROCEDURE,
            date=event_date,
            facts=facts,
            confidence=75, # Operative reports are usually high value
            citation_ids=[f.citation_id for f in facts],
            source_page_numbers=[page.page_number],
        ))

    return events, citations, warnings, skipped
