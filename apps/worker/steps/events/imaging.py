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
) -> tuple[list[Event], list[Citation], list[Warning]]:
    """Extract imaging events from imaging report pages."""
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []

    imaging_pages = [p for p in pages if p.page_type == PageType.IMAGING_REPORT]

    for page in imaging_pages:
        page_dates = dates.get(page.page_number, [])
        if not page_dates:
            continue

        # Check for impression or findings
        impression = _find_section(page.text, "Impression")
        findings = _find_section(page.text, "Findings")
        if not impression and not findings:
            continue

        event_date = page_dates[0]
        if not event_date:
            warnings.append(Warning(
                code="MISSING_DATE",
                message=f"Skipping imaging event for page {page.page_number} due to missing date",
                page=page.page_number
            ))
            continue
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

        content = impression or findings or ""
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
            citation_ids=citation_ids,
            source_page_numbers=[page.page_number],
        ))

    return events, citations, warnings
