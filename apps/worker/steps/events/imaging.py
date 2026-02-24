from __future__ import annotations
import uuid
from packages.shared.models import (
    Citation,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    ImagingDetails,
    ImagingModality,
    Page,
    PageType,
    Provider,
    SkippedEvent,
    Warning,
)
from .common import _make_citation, _make_fact, _find_section

_MODALITY_PATTERNS: list[tuple[ImagingModality, list[str]]] = [
    (ImagingModality.MRI, ["mri", "magnetic resonance"]),
    (ImagingModality.CT, ["ct ", "ct scan", "computed tomography"]),
    (ImagingModality.XRAY, ["x-ray", "xray", "radiograph"]),
    (ImagingModality.ULTRASOUND, ["ultrasound", "sonogram", "us "]),
]

def _detect_modality(text: str) -> ImagingModality:
    text_lower = text.lower()
    for mod, keywords in _MODALITY_PATTERNS:
        if any(kw in text_lower for kw in keywords):
            return mod
    return ImagingModality.OTHER

def _detect_body_part(text: str) -> str:
    """Extract body part from imaging report text."""
    body_parts = [
        "cervical spine", "lumbar spine", "thoracic spine", "spine",
        "knee", "shoulder", "hip", "ankle", "wrist", "elbow",
        "head", "brain", "chest", "abdomen", "pelvis",
        "neck", "foot", "hand", "forearm", "upper extremity", "lower extremity",
    ]
    text_lower = text.lower()
    for bp in body_parts:
        if bp in text_lower:
            return bp
    return "unspecified"

def extract_imaging_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str] = {},
) -> tuple[list[Event], list[Citation], list[Warning], list[SkippedEvent]]:
    """Extract imaging events from imaging report pages."""
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []
    skipped: list[SkippedEvent] = []

    imaging_pages = sorted(
        [p for p in pages if p.page_type == PageType.IMAGING_REPORT],
        key=lambda p: p.page_number,
    )

    # Group consecutive pages from the same provider into one imaging event.
    # A multi-page radiology report (e.g., pages 108-111) should be ONE event.
    _MAX_PAGE_GAP = 4
    page_groups: list[list[Page]] = []
    if imaging_pages:
        current_group = [imaging_pages[0]]
        for page in imaging_pages[1:]:
            prev = current_group[-1]
            prev_pid = page_provider_map.get(prev.page_number, "unknown")
            curr_pid = page_provider_map.get(page.page_number, "unknown")
            if curr_pid == prev_pid and page.page_number - prev.page_number <= _MAX_PAGE_GAP:
                current_group.append(page)
            else:
                page_groups.append(current_group)
                current_group = [page]
        page_groups.append(current_group)

    for page_group in page_groups:
        event_flags: list[str] = []

        # Gather facts from all pages in the group (up to 3 lines per page, 6 total)
        facts: list[Fact] = []
        citation_ids: list[str] = []
        impression_facts: list[Fact] = []
        combined_text = " ".join(p.text or "" for p in page_group)

        for page in page_group:
            content_section = None
            for header in ["Impression", "Findings", "Conclusion", "Summary", "Results", "Interpretation", "Report"]:
                section = _find_section(page.text, header)
                if section:
                    content_section = section
                    break
            if not content_section:
                continue
            lines = [l.strip() for l in content_section.split("\n") if l.strip()][:3]
            for line in lines:
                if len(facts) >= 6:
                    break
                cit = _make_citation(page, line)
                citations.append(cit)
                citation_ids.append(cit.citation_id)
                fact = _make_fact(line, FactKind.IMPRESSION, cit.citation_id, verbatim=True)
                facts.append(fact)
                impression_facts.append(fact)

        if not facts:
            skipped.append(SkippedEvent(
                page_numbers=[p.page_number for p in page_group],
                reason_code="NO_TRIGGER_MATCH",
                snippet=page_group[0].text[:250].strip()[:300],
            ))
            continue

        # Use the earliest date found across the group
        event_date = None
        for page in page_group:
            page_dates = dates.get(page.page_number, [])
            if page_dates:
                event_date = page_dates[0]
                break

        if not event_date:
            warnings.append(Warning(
                code="MISSING_DATE",
                message=f"Imaging event for pages {[p.page_number for p in page_group]} has no resolved date",
                page=page_group[0].page_number,
            ))
            event_flags.append("MISSING_DATE")

        modality = _detect_modality(combined_text)
        body_part = _detect_body_part(combined_text)

        provider_id = page_provider_map.get(page_group[0].page_number)
        if not provider_id and providers:
            provider_id = providers[0].provider_id
        provider_id = provider_id or "unknown"

        events.append(Event(
            event_id=uuid.uuid4().hex[:16],
            provider_id=provider_id,
            event_type=EventType.IMAGING_STUDY,
            date=event_date,
            facts=facts,
            imaging=ImagingDetails(
                modality=modality,
                body_part=body_part,
                impression=impression_facts,
            ),
            confidence=0,
            flags=event_flags,
            citation_ids=citation_ids,
            source_page_numbers=[p.page_number for p in page_group],
        ))

    # Fallback: for undated imaging events, try to inherit date from a nearby
    # same-provider event (handles multi-page imaging reports where only first page is dated).
    if events:
        dated = {e.event_id: e for e in events if e.date is not None}
        for evt in events:
            if evt.date is not None:
                continue
            # Find the nearest dated event from the same provider
            best: Event | None = None
            best_dist = 9999
            for other in dated.values():
                if other.provider_id != evt.provider_id:
                    continue
                dist = min(
                    abs(pg - opg)
                    for pg in evt.source_page_numbers
                    for opg in other.source_page_numbers
                )
                if dist < best_dist:
                    best_dist = dist
                    best = other
            if best is not None and best_dist <= 10:
                from packages.shared.models.common import EventDate, DateKind, DateSource
                evt.date = EventDate(
                    kind=DateKind.SINGLE,
                    value=best.date.value if best.date else None,
                    source=DateSource.PROPAGATED,
                )
                evt.flags = [f for f in evt.flags if f != "MISSING_DATE"]

    return events, citations, warnings, skipped
