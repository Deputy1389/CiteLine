from __future__ import annotations
import uuid
from datetime import timedelta
from packages.shared.models import (
    Citation,
    DateKind,
    DateRange,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Page,
    PageType,
    Provider,
    RunConfig,
    SkippedEvent,
    Warning,
)
from .common import _make_citation, _make_fact, _find_section

def extract_pt_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    config: RunConfig,
    page_provider_map: dict[int, str] = {},
) -> tuple[list[Event], list[Citation], list[Warning], list[SkippedEvent]]:
    """
    Extract PT events. Default: aggregate mode (bucket by window).
    """
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []
    skipped: list[SkippedEvent] = []

    pt_pages = [p for p in pages if p.page_type == PageType.PT_NOTE]
    if not pt_pages:
        return events, citations, warnings, skipped

    # Collect all PT page dates (including dateless pages)
    pt_visits_with_dates: list[tuple[Page, EventDate]] = []
    pt_visits_no_dates: list[Page] = []
    for page in pt_pages:
        page_dates = dates.get(page.page_number, [])
        if page_dates:
            pt_visits_with_dates.append((page, page_dates[0]))
        else:
            pt_visits_no_dates.append(page)

    # Emit flagged events for dateless PT pages
    for page in pt_visits_no_dates:
        snippet = page.text[:200].strip()
        cit = _make_citation(page, snippet)
        citations.append(cit)

        provider_id = page_provider_map.get(page.page_number)
        if not provider_id and providers:
            provider_id = providers[0].provider_id
        provider_id = provider_id or "unknown"

        warnings.append(Warning(
            code="MISSING_DATE",
            message=f"PT event for page {page.page_number} has no resolved date",
            page=page.page_number,
        ))

        events.append(Event(
            event_id=uuid.uuid4().hex[:16],
            provider_id=provider_id,
            event_type=EventType.PT_VISIT,
            date=None,
            facts=[_make_fact(snippet, FactKind.OTHER, cit.citation_id)],
            confidence=0,
            flags=["MISSING_DATE"],
            citation_ids=[cit.citation_id],
            source_page_numbers=[page.page_number],
        ))

    if not pt_visits_with_dates:
        return events, citations, warnings, skipped

    if config.pt_mode == "aggregate":
        # Group by provider and window
        pt_visits_with_dates.sort(key=lambda x: x[1].sort_date())
        window = timedelta(days=config.pt_aggregate_window_days)

        groups: list[list[tuple[Page, EventDate]]] = []
        current_group: list[tuple[Page, EventDate]] = [pt_visits_with_dates[0]]

        for i in range(1, len(pt_visits_with_dates)):
            prev_date = current_group[-1][1].sort_date()
            curr_date = pt_visits_with_dates[i][1].sort_date()
            if curr_date - prev_date <= window:
                current_group.append(pt_visits_with_dates[i])
            else:
                groups.append(current_group)
                current_group = [pt_visits_with_dates[i]]
        groups.append(current_group)

        for group in groups:
            visit_count = len(group)
            first_page = group[0][0]
            first_date = group[0][1]
            last_date = group[-1][1]
            all_pages = [p.page_number for p, _ in group]

            # Create citation for the summary
            snippet = f"PT sessions documented: {visit_count}"
            cit = _make_citation(first_page, snippet)
            citations.append(cit)

            # Check for progress statements
            facts: list[Fact] = [
                _make_fact(snippet, FactKind.OTHER, cit.citation_id)
            ]

            for page, _ in group[:2]:
                progress = _find_section(page.text, "Progress") or _find_section(page.text, "Goals")
                if progress:
                    prog_cit = _make_citation(page, progress)
                    citations.append(prog_cit)
                    facts.append(_make_fact(progress[:400], FactKind.OTHER, prog_cit.citation_id))

            if visit_count > 1:
                event_date = EventDate(
                    kind=DateKind.RANGE,
                    value=DateRange(start=first_date.sort_date(), end=last_date.sort_date()),
                    source=first_date.source,
                )
            else:
                event_date = first_date
            
            # Determine provider (use first page of group)
            provider_id = page_provider_map.get(first_page.page_number)
            if not provider_id and providers:
                provider_id = providers[0].provider_id
            provider_id = provider_id or "unknown"

            events.append(Event(
                event_id=uuid.uuid4().hex[:16],
                provider_id=provider_id,
                event_type=EventType.PT_VISIT,
                date=event_date,
                facts=facts[:6],
                confidence=0,
                citation_ids=[cit.citation_id for cit in citations[-len(facts):]],
                source_page_numbers=all_pages,
            ))
    else:
        # Per-visit mode
        for page, event_date in pt_visits_with_dates:
            snippet = page.text[:200].strip()
            cit = _make_citation(page, snippet)
            citations.append(cit)

            # Determine provider
            provider_id = page_provider_map.get(page.page_number)
            if not provider_id and providers:
                provider_id = providers[0].provider_id
            provider_id = provider_id or "unknown"

            events.append(Event(
                event_id=uuid.uuid4().hex[:16],
                provider_id=provider_id,
                event_type=EventType.PT_VISIT,
                date=event_date,
                facts=[_make_fact(snippet, FactKind.OTHER, cit.citation_id)],
                confidence=0,
                citation_ids=[cit.citation_id],
                source_page_numbers=[page.page_number],
            ))

    return events, citations, warnings, skipped
