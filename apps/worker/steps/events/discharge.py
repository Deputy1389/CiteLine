"""
Extract events from Discharge Summaries.
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

def extract_discharge_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str],
) -> tuple[list[Event], list[Citation], list[Warning], list[SkippedEvent]]:
    """
    Extract events from pages classified as DISCHARGE_SUMMARY.
    """
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []
    skipped: list[SkippedEvent] = []

    # Process pages identified as DISCHARGE_SUMMARY
    ds_pages = [p for p in pages if p.page_type == PageType.DISCHARGE_SUMMARY]

    for page in ds_pages:
        page_dates = dates.get(page.page_number, [])
        # Prefer discharge date (usually later date)
        # But really we want the Admission Date for the start and Discharge Date for the end.
        # For now, we'll anchor on the most prominent date found, or the first one.
        event_date = page_dates[0] if page_dates else None
        
        provider_id = page_provider_map.get(page.page_number, "unknown")
        
        facts: list[Fact] = []
        
        # Extract Diagnosis
        for header in ["Discharge Diagnosis", "Final Diagnosis", "Admitting Diagnosis"]:
            section = _find_section(page.text, header)
            if section:
                cit = _make_citation(page, section)
                citations.append(cit)
                facts.append(_make_fact(section, FactKind.DIAGNOSIS, cit.citation_id))
                break # Only one diagnosis section needed usually

        # Extract Hospital Course
        course = _find_section(page.text, "Hospital Course")
        if course:
            # Summarize if too long
            summary = course[:400].strip()
            cit = _make_citation(page, summary)
            citations.append(cit)
            facts.append(_make_fact(summary, FactKind.OTHER, cit.citation_id))
            
        # Extract Discharge Instructions / Medications
        for header in ["Discharge Instructions", "Discharge Medications"]:
            section = _find_section(page.text, header)
            if section:
                summary = section[:400].strip()
                cit = _make_citation(page, summary)
                citations.append(cit)
                facts.append(_make_fact(summary, FactKind.PLAN, cit.citation_id))

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
            event_type=EventType.DISCHARGE,
            date=event_date,
            facts=facts,
            confidence=70, # Generally high confidence if classified as DS
            citation_ids=[f.citation_id for f in facts],
            source_page_numbers=[page.page_number],
        ))

    return events, citations, warnings, skipped
