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

    imaging_pages = [p for p in pages if p.page_type == PageType.IMAGING_REPORT]

    for page in imaging_pages:
        event_flags: list[str] = []
        page_dates = dates.get(page.page_number, [])

        # Check for impression, findings, or other common report sections
        content_section = None
        for header in ["Impression", "Findings", "Conclusion", "Summary", "Results", "Interpretation", "Report"]:
            section = _find_section(page.text, header)
            if section:
                content_section = section
                break

        if not content_section:
            skipped.append(SkippedEvent(
                page_numbers=[page.page_number],
                reason_code="NO_TRIGGER_MATCH",
                snippet=page.text[:250].strip()[:300],
            ))
            continue

        event_date = page_dates[0] if page_dates else None
        if not event_date:
            warnings.append(Warning(
                code="MISSING_DATE",
                message=f"Imaging event for page {page.page_number} has no resolved date",
                page=page.page_number
            ))
            event_flags.append("MISSING_DATE")

        modality = _detect_modality(page.text)
        body_part = _detect_body_part(page.text)
        
        # Determine provider
        provider_id = page_provider_map.get(page.page_number)
        if not provider_id and providers:
            provider_id = providers[0].provider_id
        provider_id = provider_id or "unknown"

        facts: list[Fact] = []
        citation_ids: list[str] = []
        impression_facts: list[Fact] = []

        content = content_section or ""
        lines = [l.strip() for l in content.split("\n") if l.strip()][:3]
        for line in lines:
            cit = _make_citation(page, line)
            citations.append(cit)
            citation_ids.append(cit.citation_id)
            fact = _make_fact(line, FactKind.IMPRESSION, cit.citation_id, verbatim=True)
            facts.append(fact)
            impression_facts.append(fact)

        if not facts:
            continue

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
            source_page_numbers=[page.page_number],
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
