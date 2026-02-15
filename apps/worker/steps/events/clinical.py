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

def extract_clinical_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
) -> tuple[list[Event], list[Citation], list[Warning]]:
    """Extract clinical note events from pages classified as clinical/operative."""
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []

    clinical_pages = [p for p in pages if p.page_type in
                      (PageType.CLINICAL_NOTE, PageType.OPERATIVE_REPORT)]

    for page in clinical_pages:
        page_dates = dates.get(page.page_number, [])
        if not page_dates:
            continue

        event_date = page_dates[0]  # Best date
        encounter_type = _detect_encounter_type(page.text)
        provider = providers[0] if providers else None

        facts: list[Fact] = []
        citation_ids: list[str] = []

        # Extract chief complaint
        cc = _find_section(page.text, "Chief Complaint")
        if cc:
            cit = _make_citation(page, cc)
            citations.append(cit)
            citation_ids.append(cit.citation_id)
            facts.append(_make_fact(cc, FactKind.CHIEF_COMPLAINT, cit.citation_id))

        # Extract assessment/diagnosis
        for header in ["Assessment", "Diagnosis", "Diagnoses", "Impression"]:
            section = _find_section(page.text, header)
            if section:
                lines = [l.strip() for l in section.split("\n") if l.strip()][:3]
                for line in lines:
                    cit = _make_citation(page, line)
                    citations.append(cit)
                    citation_ids.append(cit.citation_id)
                    facts.append(_make_fact(line, FactKind.ASSESSMENT, cit.citation_id))
                break

        # Extract plan
        plan = _find_section(page.text, "Plan")
        if plan:
            lines = [l.strip() for l in plan.split("\n") if l.strip()][:2]
            for line in lines:
                cit = _make_citation(page, line)
                citations.append(cit)
                citation_ids.append(cit.citation_id)
                facts.append(_make_fact(line, FactKind.PLAN, cit.citation_id))

        # Extract restrictions / work status
        for header in ["Work Status", "Restrictions", "Work Restrictions"]:
            section = _find_section(page.text, header)
            if section:
                cit = _make_citation(page, section)
                citations.append(cit)
                citation_ids.append(cit.citation_id)
                facts.append(_make_fact(section, FactKind.RESTRICTION, cit.citation_id))
                break

        if not facts:
            continue

        # Cap at 6 facts
        facts = facts[:6]
        citation_ids = citation_ids[:6]

        events.append(Event(
            event_id=uuid.uuid4().hex[:16],
            provider_id=provider.provider_id if provider else "unknown",
            event_type=encounter_type,
            date=event_date,
            encounter_type_raw=encounter_type.value,
            facts=facts,
            confidence=0,  # Scored in step 10
            citation_ids=citation_ids,
            source_page_numbers=[page.page_number],
        ))

    return events, citations, warnings
