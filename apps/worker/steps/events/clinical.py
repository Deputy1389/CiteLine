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
    SkippedEvent,
    Warning,
)
from .common import _make_citation, _make_fact, _find_section
import re

_CLINICAL_INDICATORS = [
    (r"(?i)\bpain\s*(?:level|score)?\s*:?\s*(\d{1,2}/10)\b", "Pain Level"),
    (r"(?i)\b(vomiting|vomit|emesis|nausea)\b", "GI Symptom"),
    (r"(?i)\b(shortness of breath|sob|dyspnea)\b", "Respiratory Symptom"),
    (r"(?i)\b(cough|forceful coughing)\b", "Respiratory Symptom"),
    (r"(?i)\b(hospice|end of life)\b", "Care Planning"),
    (r"(?i)\b(dependent|assistance|requires help|requires partner)\b", "Functional Status"),
    (r"(?i)\b(discharge home|discharged to home)\b", "Disposition"),
]


def _detect_encounter_type(text: str) -> EventType:
    """Detect encounter type from clinical note text."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["emergency department", "ed provider", "triage", "er visit"]):
        return EventType.ER_VISIT
    if any(kw in text_lower for kw in ["discharge summary", "discharged"]):
        return EventType.HOSPITAL_DISCHARGE
    if any(kw in text_lower for kw in ["admitted", "admission", "triage", "er admission", "inpatient admission"]):
        return EventType.HOSPITAL_ADMISSION
    if any(kw in text_lower for kw in [
        "oncology floor", "nursing flowsheet", "mar ", "medication administration record",
        "i&o", "daily progress note", "flowsheet", "vital signs flowsheet"
    ]):
        return EventType.INPATIENT_DAILY_NOTE
    if any(kw in text_lower for kw in ["operative report", "procedure"]):
        return EventType.PROCEDURE
    return EventType.OFFICE_VISIT

from apps.worker.lib.grouping import group_clinical_pages

PRIORITY_MAP = {
    EventType.ER_VISIT: 6,
    EventType.HOSPITAL_ADMISSION: 5,
    EventType.HOSPITAL_DISCHARGE: 4,
    EventType.INPATIENT_DAILY_NOTE: 3,
    EventType.PROCEDURE: 2,
    EventType.OFFICE_VISIT: 1,
}

def extract_clinical_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str] = {},
) -> tuple[list[Event], list[Citation], list[Warning], list[SkippedEvent]]:
    """Extract clinical note events using block grouping."""
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []
    skipped: list[SkippedEvent] = []

    # 1. Group pages into blocks
    blocks = group_clinical_pages(pages, dates, providers, page_provider_map)

    for block in blocks:
        event_flags: list[str] = []

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
                message=f"Event for pages {block.page_numbers} has no resolved date",
                page=block.pages[0].page_number
            ))
            event_flags.append("MISSING_DATE")
        
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

        if not block_facts:
            # Record as skipped for debug visibility (P1)
            snippet = block.pages[0].text[:250].strip() if block.pages else ""
            skipped.append(SkippedEvent(
                page_numbers=block.page_numbers,
                reason_code="NO_FACTS",
                snippet=snippet[:300],
            ))
            continue
             
        # Cap facts
        block_facts = block_facts[:12]
        block_citation_ids = block_citation_ids[:12]

        events.append(Event(
            event_id=uuid.uuid4().hex[:16],
            provider_id=provider_id,
            event_type=encounter_type,
            date=event_date,
            encounter_type_raw=encounter_type.value,
            facts=block_facts,
            confidence=0,
            flags=event_flags,
            citation_ids=block_citation_ids,
            source_page_numbers=block.page_numbers,
        ))

    return events, citations, warnings, skipped

def _get_best_date(page_dates: list[EventDate]) -> EventDate | None:
    if not page_dates:
        return None
    tier1 = [d for d in page_dates if d.source == "tier1"]
    if tier1:
        return tier1[0]
    return page_dates[0]

def _is_boilerplate(text: str) -> bool:
    """Filter out common medical record legends, instructions, and non-clinical text."""
    boilerplate_patterns = [
        r"(?i)see nursing notes",
        r"(?i)fluid measurements legend",
        r"(?i)mar legend",
        r"(?i)electronically signed by",
        r"(?i)confidential medical record",
        r"(?i)page \d+ of \d+",
        r"(?i)continued on next page",
        r"(?i)this document contains privileged",
        r"_{5,}", # Long underscores (forms)
        r"[-]{5,}",
    ]
    return any(re.search(p, text) for p in boilerplate_patterns)

def _extract_page_content(page: Page) -> tuple[list[Fact], list[Citation]]:
    """Extract facts/citations from a single page."""
    facts: list[Fact] = []
    citations: list[Citation] = []
    
    # ── Strategy 0: Boilerplate Check ─────────────────────────────────
    if len(page.text.strip()) < 50 or _is_boilerplate(page.text):
        return [], []

    # ── Strategy 1: Explicit Indicators (Keywords) ────────────────────
    indicator_facts, indicator_cits = _extract_indicators(page)
    facts.extend(indicator_facts)
    citations.extend(indicator_cits)

    # ── Strategy 2: Sectional extraction ──────────────────────────────
    cc = _find_section(page.text, "Chief Complaint")
    if cc:
        cit = _make_citation(page, cc)
        citations.append(cit)
        facts.append(_make_fact(cc, FactKind.CHIEF_COMPLAINT, cit.citation_id))

    # Extract HPI narrative
    for header in ["History of Present Illness", "HPI"]:
        hpi = _find_section(page.text, header)
        if hpi:
            # Take first 400 chars as summary
            summary = hpi[:400].strip()
            cit = _make_citation(page, summary)
            citations.append(cit)
            facts.append(_make_fact(summary, FactKind.OTHER, cit.citation_id))
            break

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

    # Extract medications
    for header in ["Medications", "Current Medications", "Medications Prescribed", "Rx"]:
        meds = _find_section(page.text, header)
        if meds:
            lines = [l.strip() for l in meds.split("\n") if l.strip()][:5]
            for line in lines:
                cit = _make_citation(page, line)
                citations.append(cit)
                facts.append(_make_fact(line, FactKind.MEDICATION, cit.citation_id))
            break

    # Extract procedures performed
    for header in ["Procedures Performed", "Procedures", "Procedure"]:
        procs = _find_section(page.text, header)
        if procs:
            lines = [l.strip() for l in procs.split("\n") if l.strip()][:3]
            for line in lines:
                cit = _make_citation(page, line)
                citations.append(cit)
                facts.append(_make_fact(line, FactKind.PROCEDURE_NOTE, cit.citation_id))
            break

    # Extract vitals summary
    for header in ["Vital Signs", "Vitals"]:
        vitals = _find_section(page.text, header)
        if vitals:
            # Condense into single fact
            summary = " | ".join(l.strip() for l in vitals.split("\n") if l.strip())[:400]
            cit = _make_citation(page, summary)
            citations.append(cit)
            facts.append(_make_fact(summary, FactKind.OTHER, cit.citation_id))
            break

    # Extract restrictions / work status
    for header in ["Work Status", "Restrictions", "Work Restrictions"]:
        section = _find_section(page.text, header)
        if section:
            cit = _make_citation(page, section)
            citations.append(cit)
            facts.append(_make_fact(section, FactKind.RESTRICTION, cit.citation_id))
            break
            
    return facts, citations

def _extract_indicators(page: Page) -> tuple[list[Fact], list[Citation]]:
    """Scan for specific clinical markers that might be buried in text."""
    facts: list[Fact] = []
    citations: list[Citation] = []
    text = page.text
    
    seen_snippets = set()

    for pattern, label in _CLINICAL_INDICATORS:
        for m in re.finditer(pattern, text):
            # Extract sentence-like context
            start = max(0, m.start() - 50)
            end = min(len(text), m.end() + 100)
            snippet = text[start:end].replace("\n", " ").strip()
            
            # Basic dedupe of overlapping markers on same page
            if snippet in seen_snippets: continue
            seen_snippets.add(snippet)

            cit = _make_citation(page, snippet)
            citations.append(cit)
            facts.append(_make_fact(f"{label}: {snippet}", FactKind.OTHER, cit.citation_id))
            
    return facts, citations
