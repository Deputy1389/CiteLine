from __future__ import annotations
import uuid
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
    Warning,
)
from .common import _make_citation, _make_fact, _find_section

def _detect_encounter_type(text: str) -> EventType:
    """Detect encounter type from clinical note text."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["emergency department", "ed provider", "triage", "er visit"]):
        return EventType.ER_VISIT
    if any(kw in text_lower for kw in ["discharge summary", "discharged"]):
        return EventType.HOSPITAL_DISCHARGE
    if any(kw in text_lower for kw in ["admitted", "admission"]):
        return EventType.HOSPITAL_ADMISSION
    if any(kw in text_lower for kw in ["operative report", "procedure"]):
        return EventType.PROCEDURE
    return EventType.OFFICE_VISIT

from apps.worker.lib.grouping import group_clinical_pages

PRIORITY_MAP = {
    EventType.ER_VISIT: 5,
    EventType.HOSPITAL_ADMISSION: 4,
    EventType.HOSPITAL_DISCHARGE: 3,
    EventType.PROCEDURE: 2,
    EventType.OFFICE_VISIT: 1,
}

def extract_clinical_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str] = {},
) -> tuple[list[Event], list[Citation], list[Warning]]:
    """Extract clinical note events using block grouping."""
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []

    # 1. Group pages into blocks
    blocks = group_clinical_pages(pages, dates, providers, page_provider_map)

    for block in blocks:
        # 2. Determine Block Metadata
        # Date: Use block primary date, fallback to first page best date
        if block.primary_date:
            event_date = block.primary_date
        else:
            # Should not happen if grouping worked well, but valid fallback
            event_date = _get_best_date(dates.get(block.pages[0].page_number, []))
            
        if not event_date:
             warnings.append(Warning(
                 code="MISSING_DATE",
                 message=f"Skipping event for pages {block.page_numbers} due to missing date",
                 page=block.pages[0].page_number
             ))
             continue
        
        # Provider: Use block primary provider, fallback to first available
        provider_id = block.primary_provider_id
        if not provider_id:

            # Fallback to first non-None
            for p in block.pages:
                pid = page_provider_map.get(p.page_number)
                if pid:
                    provider_id = pid
                    break
        if not provider_id and providers:
            provider_id = providers[0].provider_id
        provider_id = provider_id or "unknown"

        # Encounter Type: Max priority from all pages
        encounter_type = EventType.OFFICE_VISIT
        current_prio = 1
        
        for page in block.pages:
            etype = _detect_encounter_type(page.text)
            prio = PRIORITY_MAP.get(etype, 0)
            if prio > current_prio:
                encounter_type = etype
                current_prio = prio
                
        # 3. Extract Facts & Citations from all pages
        # We aggregate all facts/citations
        block_facts: list[Fact] = []
        block_citation_ids: list[str] = []
        
        for page in block.pages:
            # Reuse page-level logic but aggregate
            page_facts, page_cits = _extract_page_content(page)
            block_facts.extend(page_facts)
            citations.extend(page_cits)
            block_citation_ids.extend([c.citation_id for c in page_cits])

        # If no facts found, maybe create a generic one? 
        # Or if we have a valid block, we should create an event even with just metadata?
        # Current logic continues if no facts. Let's keep that but maybe loosen it?
        # User requirement: "Group pages... Create one event per block"
        # If block exists, we probably want an event.
        if not block_facts:
            # Minimal fact? "Clinical Note for Date"
            pass

        if not block_facts:
             # Try to ensure at least one citation if possible?
             # User said: "Prefer citations from the page section containing date..."
             # If no facts found, we skip event?
             # Let's stick to original logic: if no facts, continue.
             continue
             
        # Cap facts? maybe higher cap for block?
        # Original was 6 per page. Maybe 10 per block?
        block_facts = block_facts[:12]
        block_citation_ids = block_citation_ids[:12]

        print(f"DEBUG: Creating event for block {block.page_numbers}, date={event_date}")
        events.append(Event(
            event_id=uuid.uuid4().hex[:16],
            provider_id=provider_id,
            event_type=encounter_type,
            date=event_date,
            encounter_type_raw=encounter_type.value,
            facts=block_facts,
            confidence=0,
            citation_ids=block_citation_ids,
            source_page_numbers=block.page_numbers,
        ))

    return events, citations, warnings

def _get_best_date(page_dates: list[EventDate]) -> EventDate | None:
    if not page_dates:
        return None
    tier1 = [d for d in page_dates if d.source == "tier1"]
    if tier1:
        return tier1[0]
    return page_dates[0]

def _extract_page_content(page: Page) -> tuple[list[Fact], list[Citation]]:
    """Extract facts/citations from a single page."""
    facts: list[Fact] = []
    citations: list[Citation] = []
    
    # Extract chief complaint
    cc = _find_section(page.text, "Chief Complaint")
    if cc:
        cit = _make_citation(page, cc)
        citations.append(cit)
        facts.append(_make_fact(cc, FactKind.CHIEF_COMPLAINT, cit.citation_id))

    # Extract assessment/diagnosis
    for header in ["Assessment", "Diagnosis", "Diagnoses", "Impression"]:
        section = _find_section(page.text, header)
        if section:
            lines = [l.strip() for l in section.split("\n") if l.strip()][:3]
            for line in lines:
                cit = _make_citation(page, line)
                citations.append(cit)
                facts.append(_make_fact(line, FactKind.ASSESSMENT, cit.citation_id))
            break

    # Extract plan
    plan = _find_section(page.text, "Plan")
    if plan:
        lines = [l.strip() for l in plan.split("\n") if l.strip()][:2]
        for line in lines:
            cit = _make_citation(page, line)
            citations.append(cit)
            facts.append(_make_fact(line, FactKind.PLAN, cit.citation_id))

    # Extract restrictions / work status
    for header in ["Work Status", "Restrictions", "Work Restrictions"]:
        section = _find_section(page.text, header)
        if section:
            cit = _make_citation(page, section)
            citations.append(cit)
            facts.append(_make_fact(section, FactKind.RESTRICTION, cit.citation_id))
            break
            
    return facts, citations
