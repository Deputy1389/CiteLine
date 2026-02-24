
from __future__ import annotations
from typing import Any
from packages.shared.models import Event, Provider, Fact, FactKind, EventType as DomainEventType, DateStatus as DomainDateStatus
from datetime import date

def to_skill_event(evt: Event, providers: list[Provider]) -> dict[str, Any]:
    """Convert a domain Event to the LLM Skill Event schema format."""
    
    # Map EventType
    type_map = {
        DomainEventType.IMAGING_STUDY: "IMAGING_STUDY",
        DomainEventType.ER_VISIT: "ER_VISIT",
        DomainEventType.OFFICE_VISIT: "CLINICAL_NOTE",
        DomainEventType.PT_VISIT: "THERAPY_VISIT",
        DomainEventType.PROCEDURE: "PROCEDURE",
        DomainEventType.LAB_RESULT: "LAB_RESULT",
        DomainEventType.BILLING_EVENT: "BILLING_EVENT",
        DomainEventType.HOSPITAL_ADMISSION: "CLINICAL_NOTE",
        DomainEventType.HOSPITAL_DISCHARGE: "CLINICAL_NOTE",
        DomainEventType.INPATIENT_DAILY_NOTE: "CLINICAL_NOTE",
    }
    event_type = type_map.get(evt.event_type, "UNKNOWN")
    
    # Map DateStatus
    date_status = "UNDATED"
    if evt.date:
        status_map = {
            "explicit": "EXPLICIT",
            "range": "RANGE",
            "ambiguous": "AMBIGUOUS",
            "propagated": "PROPAGATED",
            "undated": "UNDATED"
        }
        date_status = status_map.get(evt.date.status, "UNDATED")

    # Date ISO
    date_iso = None
    date_range = None
    if evt.date and evt.date.value:
        if isinstance(evt.date.value, date):
            date_iso = evt.date.value.isoformat()
        elif hasattr(evt.date.value, "start"):
            date_range = {
                "start_date_iso": evt.date.value.start.isoformat(),
                "end_date_iso": evt.date.value.end.isoformat() if evt.date.value.end else evt.date.value.start.isoformat()
            }

    # Snippets
    snippets = []
    for i, f in enumerate(evt.facts):
        kind_map = {
            FactKind.FINDING: "FINDING",
            FactKind.IMPRESSION: "IMPRESSION",
            FactKind.ASSESSMENT: "ASSESSMENT",
            FactKind.PLAN: "PLAN",
            FactKind.DIAGNOSIS: "DIAGNOSIS",
            FactKind.CHIEF_COMPLAINT: "HPI",
            FactKind.PAIN_SCORE: "VITALS",
        }
        snippets.append({
            "snippet_id": f"snip_{evt.event_id}_{i}",
            "text": f.text,
            "kind": kind_map.get(f.kind, "OTHER"),
            "technical_noise": getattr(f, "technical_noise", False)
        })

    if not snippets:
        snippets.append({
            "snippet_id": f"snip_{evt.event_id}_0",
            "text": "[No text detected]",
            "kind": "OTHER"
        })

    # Provider
    provider_name = "Unknown"
    if evt.provider_id:
        p_match = [p for p in providers if p.provider_id == evt.provider_id]
        if p_match:
            provider_name = p_match[0].normalized_name

    return {
        "event_id": evt.event_id,
        "event_type": event_type,
        "date_status": date_status,
        "date_iso": date_iso,
        "date_range": date_range,
        "facility": None, # Future: extract from provider
        "clinician": provider_name,
        "citation_count": len(evt.citation_ids),
        "confidence": evt.confidence,
        "exportable": evt.confidence >= 30, # Match RunConfig default
        "tags": [], # Potential future enhancement
        "snippets": snippets
    }
