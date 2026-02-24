"""
Step 10 — Confidence scoring + flags.
Compute Event.confidence (0–100) based on date tier, provider, encounter cues, content anchors.
"""
from __future__ import annotations

from packages.shared.models import (
    DateSource,
    Event,
    EventType,
    FactKind,
    DateStatus,
    RunConfig,
    Warning,
)
from apps.worker.quality.text_quality import should_quarantine_fact


def score_event(event: Event) -> int:
    """Compute confidence score for an event (0–100)."""
    score = 0

    # Date status contribution
    if event.date:
        if event.date.status == DateStatus.EXPLICIT:
            score += 35
        elif event.date.status == DateStatus.RANGE:
            score += 25
        elif event.date.status == DateStatus.PROPAGATED:
            score += 15
        elif event.date.status == DateStatus.AMBIGUOUS:
            score += 10
        elif event.date.status == DateStatus.UNDATED:
            score -= 50  # Heavy penalty for undated status

    # Provider confidence
    if event.provider_id and event.provider_id != "unknown":
        score += 20

    # Encounter type strong cue
    strong_types = {
        EventType.ER_VISIT, EventType.HOSPITAL_ADMISSION,
        EventType.HOSPITAL_DISCHARGE, EventType.PROCEDURE,
        EventType.INPATIENT_DAILY_NOTE,
    }
    if event.event_type in strong_types:
        score += 15

    # Content anchors — +7 each, max 21 (increased from 5/15)
    anchor_kinds = {FactKind.CHIEF_COMPLAINT, FactKind.ASSESSMENT, FactKind.PLAN, FactKind.IMPRESSION}
    anchor_count = sum(1 for f in event.facts if f.kind in anchor_kinds)
    score += min(anchor_count * 7, 21)

    # Clinical content density — bonus for diagnosis, procedure, medication facts
    clinical_kinds = {FactKind.DIAGNOSIS, FactKind.PROCEDURE, FactKind.MEDICATION}
    clinical_count = sum(1 for f in event.facts if f.kind in clinical_kinds)
    score += min(clinical_count * 4, 12)  # Up to +12 for clinical density

    # Fact richness — reward events with ≥3 facts (increased from 5 to 8)
    if len(event.facts) >= 3:
        score += 8

    # Citation coverage — reward events with multiple citations (increased from 5 to 10)
    if len(event.citation_ids) >= 2:
        score += 10
    elif len(event.citation_ids) >= 4:
        score += 5  # Extra bonus for heavily cited events

    # multi-page events are stronger
    if len(event.source_page_numbers) > 1:
        score += 5

    # NEW: Granular timestamp boost (Crucial for flowsheet data)
    if event.date and event.date.extensions and event.date.extensions.get("time"):
        score += 25

    return max(0, min(score, 100))


def apply_ocr_quarantine(events: list[Event]) -> int:
    """
    Clause VI — OCR Quarantine pass.
    Mark facts that fail quality thresholds as technical_noise=True.
    Facts are NEVER deleted; they are suppressed from attorney-facing output
    but remain in the raw evidence graph for audit.
    Returns the count of quarantined facts.
    """
    quarantined = 0
    for event in events:
        for fact in event.facts:
            if not fact.technical_noise and should_quarantine_fact(fact.text):
                fact.technical_noise = True
                quarantined += 1
    return quarantined


def apply_confidence_scoring(
    events: list[Event],
    config: RunConfig,
) -> tuple[list[Event], list[Warning]]:
    """
    Score all events and apply flags.
    Returns (events_with_scores, warnings).
    """
    warnings: list[Warning] = []

    # Clause VI: mark OCR noise facts before scoring so noisy events score lower
    apply_ocr_quarantine(events)

    for event in events:
        event.confidence = score_event(event)

        # Apply flags
        if event.confidence < config.event_confidence_min_export:
            event.flags.append("LOW_CONFIDENCE")

    return events, warnings


def filter_for_export(
    events: list[Event],
    config: RunConfig,
) -> list[Event]:
    """
    Filter events based on low_confidence_event_behavior.
    Returns exportable events.
    """
    if config.low_confidence_event_behavior == "include_with_flag":
        return events

    return [e for e in events if e.confidence >= config.event_confidence_min_export]
