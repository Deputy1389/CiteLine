"""
Step 7 — Clinical Event Extraction (Refactored)

Primary orchestrator for extracting clinical encounters from page blocks.
"""
from __future__ import annotations
import uuid
import re
import os
from datetime import date
from packages.shared.models import (
    Citation, Event, EventDate, EventType, Fact, FactKind,
    Page, DateKind, DateSource, Provider, SkippedEvent,
    Warning as PipelineWarning
)
from apps.worker.steps.events.common import _make_citation, _make_fact, _find_section
from apps.worker.steps.step06_dates import make_partial_date
from apps.worker.quality.text_quality import _EMR_LABEL_PREFIX_RE, is_garbage
from apps.worker.lib.grouping import group_clinical_pages

# Modular Imports
from apps.worker.steps.events.clinical_patterns import (
    DATE_LINE_RE, TIME_LINE_RE, DATE_TIME_LINE_RE, DATE_TIME_INLINE_RE,
    AUTHOR_RE, CLINICAL_INDICATORS, is_boilerplate_line
)
from apps.worker.steps.events.encounter_classifier import detect_encounter_type, PRIORITY_MAP
from apps.worker.steps.events.clinical_assembler import append_to_event

def extract_clinical_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str] = {},
) -> tuple[list[Event], list[Citation], list[PipelineWarning], list[SkippedEvent]]:
    """Extract clinical note events using block grouping."""
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[PipelineWarning] = []
    skipped: list[SkippedEvent] = []

    # 1. Group pages into blocks
    blocks = group_clinical_pages(pages, dates, providers, page_provider_map)

    for block in blocks:
        block_events, block_citations = _extract_block_events(block, page_provider_map, providers)
        
        if not block_events:
            block_facts: list[Fact] = []
            for page in block.pages:
                page_facts, page_cits = _extract_page_content(page)
                block_facts.extend(page_facts)
                citations.extend(page_cits)

            if not block_facts:
                skipped.append(SkippedEvent(
                    page_numbers=block.page_numbers,
                    reason_code="NO_FACTS",
                    snippet=block.pages[0].text[:200] if block.pages else "No text",
                ))
                continue

            provider_id = (
                block.primary_provider_id
                or (page_provider_map.get(block.pages[0].page_number) if block.pages else None)
                or (providers[0].provider_id if providers else "unknown")
            )
            etype = detect_encounter_type(" ".join(f.text for f in block_facts))

            candidates: list[EventDate] = []
            for p in block.pages:
                candidates.extend(dates.get(p.page_number, []) or [])

            event_date: EventDate | None = None
            event_flags: list[str] = []
            
            if candidates:
                if etype == EventType.HOSPITAL_DISCHARGE:
                    event_date = max(candidates, key=lambda d: d.sort_key())
                elif etype == EventType.HOSPITAL_ADMISSION:
                    explicit_adm = [d for d in candidates if d.source == DateSource.TIER1 or d.status == "explicit"]
                    if explicit_adm:
                        event_date = min(explicit_adm, key=lambda d: d.sort_key())
                    else:
                        event_date = candidates[0]
                        event_flags.append("UNVERIFIED_ADMISSION_DATE")
                else:
                    full_dates = [d for d in candidates if d.value is not None]
                    event_date = full_dates[0] if full_dates else (block.primary_date or min(candidates, key=lambda d: d.sort_key()))
            else:
                event_date = block.primary_date

            if not event_date or (event_date.status == "undated"):
                warnings.append(PipelineWarning(
                    code="MISSING_DATE",
                    message=f"Event for pages {block.page_numbers} has no resolved date",
                    page=block.pages[0].page_number,
                ))
                event_flags.append("MISSING_DATE")

            events.append(Event(
                event_id=uuid.uuid4().hex[:16],
                provider_id=provider_id,
                event_type=etype,
                date=event_date,
                facts=block_facts[:12],
                confidence=80,
                flags=event_flags,
                citation_ids=[f.citation_id for f in block_facts[:12]],
                source_page_numbers=block.page_numbers,
            ))
            continue

        events.extend(block_events)
        citations.extend(block_citations)

    assessment_findings = _extract_assessment_findings(pages)
    if events and assessment_findings:
        if not events[0].extensions: events[0].extensions = {}
        events[0].extensions["assessment_findings"] = assessment_findings

    return events, citations, warnings, skipped

def _extract_page_content(page: Page) -> tuple[list[Fact], list[Citation]]:
    facts, citations = [], []
    lines = page.text.split("\n")
    for line in lines:
        if is_boilerplate_line(line) or is_garbage(line): continue
        cit = _make_citation(page, line)
        citations.append(cit)
        facts.append(_make_fact(line, FactKind.OTHER, cit.citation_id))
    return facts, citations

def _extract_block_events(block, page_provider_map, providers):
    """
    Line-by-line scanning inside a block to detect intra-block date/time transitions.
    Especially important for flowsheet-style records.
    """
    events: list[Event] = []
    citations: list[Citation] = []
    
    current_event: Event | None = None
    current_date: EventDate | None = block.primary_date
    
    provider_id = (
        block.primary_provider_id
        or (page_provider_map.get(block.pages[0].page_number) if block.pages else None)
        or (providers[0].provider_id if providers else "unknown")
    )

    for page in block.pages:
        lines = page.text.split("\n")
        for line in lines:
            if is_boilerplate_line(line) or is_garbage(line):
                continue
            
            # 1. Detect Date/Time transitions
            # "9/24 1600 ..."
            dt_match = DATE_TIME_LINE_RE.search(line)
            if dt_match:
                # Close current event
                current_event = None
                
                # New date?
                mm, dd, hhmm, rest = dt_match.groups()
                # Create a synthetic EventDate
                # Use year from primary_date or current year
                year = block.primary_date.value.year if block.primary_date and block.primary_date.value else date.today().year
                try:
                    new_val = date(year, int(mm), int(dd))
                    current_date = EventDate(
                        value=new_val,
                        status="explicit",
                        source=DateSource.TIER1
                    )
                except:
                    pass
                
                # Create new event
                current_event = Event(
                    event_id=uuid.uuid4().hex[:16],
                    provider_id=provider_id,
                    event_type=detect_encounter_type(line),
                    date=current_date,
                    facts=[],
                    confidence=85,
                    source_page_numbers=[page.page_number],
                )
                events.append(current_event)
                append_to_event(current_event, line, page, citations)
                continue

            # 2. Add to existing or create default
            if not current_event:
                current_event = Event(
                    event_id=uuid.uuid4().hex[:16],
                    provider_id=provider_id,
                    event_type=detect_encounter_type(line),
                    date=current_date,
                    facts=[],
                    confidence=80,
                    source_page_numbers=[page.page_number],
                )
                events.append(current_event)
            
            append_to_event(current_event, line, page, citations)

    # Filter out empty events
    return [e for e in events if e.facts], citations

def _extract_assessment_findings(pages: list[Page]) -> list[str]:
    findings = []
    for page in pages:
        assessment = _find_section(page.text, "Assessment")
        if assessment: findings.append(assessment)
    return findings
