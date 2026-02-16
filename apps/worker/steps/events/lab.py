"""
Extract events from Lab Reports.
"""
from __future__ import annotations

import re
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

# Common lab tests to look for
_LAB_TESTS = [
    "WBC", "White Blood Cell", "RBC", "Red Blood Cell", "Hemoglobin", "Hematocrit",
    "Platelet", "Glucose", "Calcium", "Sodium", "Potassium", "Chloride",
    "CO2", "BUN", "Creatinine", "Albumin", "Bilirubin", "Alkaline Phosphatase",
    "AST", "ALT", "Protein", "Globulin",
]

def extract_lab_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str],
) -> tuple[list[Event], list[Citation], list[Warning], list[SkippedEvent]]:
    """
    Extract events from pages classified as LAB_REPORT.
    """
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []
    skipped: list[SkippedEvent] = []

    # Process pages identified as LAB_REPORT
    lab_pages = [p for p in pages if p.page_type == PageType.LAB_REPORT]

    for page in lab_pages:
        page_dates = dates.get(page.page_number, [])
        # Prefer collection date or result date
        event_date = page_dates[0] if page_dates else None
        
        provider_id = page_provider_map.get(page.page_number, "unknown")
        
        # Extract specific tests found on page
        found_tests = []
        text_lower = page.text.lower()
        for test in _LAB_TESTS:
            if test.lower() in text_lower:
                found_tests.append(test)
        
        # If no tests found, maybe just a summary
        facts = []
        if found_tests:
            # Create a summary fact
            summary_text = f"Labs found: {', '.join(found_tests[:5])}"
            if len(found_tests) > 5:
                summary_text += f" (+{len(found_tests)-5} more)"
            
            cit = _make_citation(page, summary_text) # Simplified citation
            citations.append(cit)
            facts.append(_make_fact(summary_text, FactKind.LAB, cit.citation_id))
        else:
            # Fallback for generic lab text
            if "specimen" in text_lower or "reference range" in text_lower:
                cit = _make_citation(page, "Lab report content detected")
                citations.append(cit)
                facts.append(_make_fact("Lab report content", FactKind.LAB, cit.citation_id))
        
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
            event_type=EventType.LAB_RESULT,
            date=event_date,
            facts=facts,
            confidence=60,
            citation_ids=[f.citation_id for f in facts],
            source_page_numbers=[page.page_number],
        ))

    return events, citations, warnings, skipped
