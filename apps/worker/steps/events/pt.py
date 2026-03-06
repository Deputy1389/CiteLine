import re
import textwrap
import uuid
from datetime import date, timedelta
from packages.shared.models import (
    Citation,
    DateKind,
    DateRange,
    Event,
    EventDate,
    DateStatus,
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


def _resolved_pt_group_event_date(group_dates: list[EventDate]) -> EventDate | None:
    explicit_dates: list[date] = []
    partial_dates: list[EventDate] = []
    fallback_dates: list[EventDate] = []

    for ed in group_dates:
        if ed is None:
            continue
        fallback_dates.append(ed)
        value = ed.value
        if isinstance(value, date):
            if value.year > 1900:
                explicit_dates.append(value)
            continue
        if isinstance(value, DateRange):
            if value.start and value.start.year > 1900:
                explicit_dates.append(value.start)
            if value.end and value.end.year > 1900:
                explicit_dates.append(value.end)
            continue
        ext = ed.extensions or {}
        if ext.get("partial_date") or ed.partial_month is not None:
            partial_dates.append(ed)

    if len(explicit_dates) >= 2:
        start = min(explicit_dates)
        end = max(explicit_dates)
        return EventDate(
            kind=DateKind.RANGE,
            value=DateRange(start=start, end=end),
            source=group_dates[0].source,
            status=DateStatus.RANGE,
        )

    if len(explicit_dates) == 1:
        return EventDate(
            kind=DateKind.SINGLE,
            value=explicit_dates[0],
            source=group_dates[0].source,
            status=DateStatus.PROPAGATED,
        )

    if partial_dates:
        return partial_dates[0]

    return fallback_dates[0] if fallback_dates else None

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
    max_facts = max(1, int(config.pt_max_facts))

    # Also pick up pages that were classified as CLINICAL_NOTE but contain PT content
    # (happens when PT keywords score below threshold but medical fallback fires)
    _PT_CONTENT_RE = re.compile(
        r"\b(physical therapy|therapist|range of motion|rom[:\s]|treat(?:ment)?\s*dx|hep\b|"
        r"therapeutic exercise|home exercise|manual therapy|patient tolerated|repetitions|set\(s\))\b",
        re.IGNORECASE
    )
    pt_pages = [
        p for p in pages
        if p.page_type == PageType.PT_NOTE
        or (p.page_type == PageType.CLINICAL_NOTE and _PT_CONTENT_RE.search(p.text or ""))
    ]
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
        # Extract more meaningful content for PT notes
        facts = []

        # Look for progress/goals
        progress = _find_section(page.text, "Progress") or _find_section(page.text, "Goals") or _find_section(page.text, "Subjective")
        if progress:
            snippet = textwrap.shorten(progress.strip(), width=200, placeholder="...")
        else:
            snippet = textwrap.shorten(page.text.strip(), width=200, placeholder="...")

        cit = _make_citation(page, snippet)
        citations.append(cit)
        facts.append(_make_fact(snippet, FactKind.OTHER, cit.citation_id))

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
            facts=facts[:max_facts],
            confidence=0,
            flags=["MISSING_DATE"],
            citation_ids=[f.citation_id for f in facts[:max_facts] if f.citation_id],
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
            # Extract clinical keywords for a richer summary
            group_text = " ".join(p.text.lower() for p, _ in group)
            keywords = []
            if "rom" in group_text or "range of motion" in group_text: keywords.append("ROM")
            if "exercise" in group_text: keywords.append("Exercise")
            if "gait" in group_text: keywords.append("Gait")
            if "strength" in group_text: keywords.append("Strength")

            kw_str = f" ({', '.join(keywords)})" if keywords else ""
            snippet = f"Aggregated PT sessions ({visit_count} encounters){kw_str}"
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
                event_date = _resolved_pt_group_event_date([event_date for _, event_date in group])
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
                facts=facts[:max_facts],
                confidence=0,
                citation_ids=[f.citation_id for f in facts[:max_facts] if f.citation_id],
                source_page_numbers=all_pages,
            ))
    else:
        # Per-visit mode â€” one event per PT page (maximum density)
        for page, event_date in pt_visits_with_dates:
            facts: list[Fact] = []

            # Ordered section extraction for clinical richness
            for section_name, fact_kind in [
                ("Assessment",  FactKind.ASSESSMENT),
                ("Objective",   FactKind.ASSESSMENT),
                ("Plan",        FactKind.PLAN),
                ("Progress",    FactKind.OTHER),
                ("Goals",       FactKind.OTHER),
                ("Subjective",  FactKind.OTHER),
            ]:
                section_text = _find_section(page.text, section_name)
                if section_text:
                    snippet = textwrap.shorten(section_text.strip(), width=350, placeholder="...")
                    cit = _make_citation(page, snippet)
                    citations.append(cit)
                    facts.append(_make_fact(snippet, fact_kind, cit.citation_id))

            # Extract ROM values inline if not already captured
            import re as _re
            rom_match = _re.search(
                r"((?:cervical|lumbar|thoracic)?\s*(?:rom|range of motion)[^\n]{0,120})",
                page.text, _re.IGNORECASE
            )
            if rom_match and not any("rom" in f.text.lower() for f in facts):
                snippet = textwrap.shorten(rom_match.group(1).strip(), width=200, placeholder="...")
                cit = _make_citation(page, snippet)
                citations.append(cit)
                facts.append(_make_fact(snippet, FactKind.OTHER, cit.citation_id))

            # Extract pain score if present
            pain_match = _re.search(
                r"(pain(?:\s*(?:score|level|severity))?\s*[:=]?\s*\d+\s*/\s*10[^\n]{0,80})",
                page.text, _re.IGNORECASE
            )
            if pain_match and not any("pain" in f.text.lower() and "/10" in f.text for f in facts):
                snippet = textwrap.shorten(pain_match.group(1).strip(), width=200, placeholder="...")
                cit = _make_citation(page, snippet)
                citations.append(cit)
                facts.append(_make_fact(snippet, FactKind.OTHER, cit.citation_id))

            # Fallback to page text if nothing extracted
            if not facts:
                snippet = textwrap.shorten(page.text.strip(), width=250, placeholder="...")
                cit = _make_citation(page, snippet)
                citations.append(cit)
                facts.append(_make_fact(snippet, FactKind.OTHER, cit.citation_id))

            provider_id = page_provider_map.get(page.page_number)
            if not provider_id and providers:
                provider_id = providers[0].provider_id
            provider_id = provider_id or "unknown"

            events.append(Event(
                event_id=uuid.uuid4().hex[:16],
                provider_id=provider_id,
                event_type=EventType.PT_VISIT,
                date=event_date,
                facts=facts[:max_facts],
                confidence=0,
                citation_ids=[f.citation_id for f in facts[:max_facts] if f.citation_id],
                source_page_numbers=[page.page_number],
            ))

    return events, citations, warnings, skipped
