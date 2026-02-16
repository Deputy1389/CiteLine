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
    RunConfig,
    Warning,
)


def score_event(event: Event) -> int:
    """Compute confidence score for an event (0–100)."""
    score = 0

    # Date tier contribution
    if event.date:
        if event.date.source == DateSource.TIER1:
            score += 35
        elif event.date.source == DateSource.TIER2:
            score += 20
        elif event.date.source in (DateSource.PROPAGATED, DateSource.ANCHOR):
            score += 15

    # Provider confidence
    if event.provider_id and event.provider_id != "unknown":
        score += 20

    # Encounter type strong cue
    strong_types = {
        EventType.ER_VISIT, EventType.HOSPITAL_ADMISSION,
        EventType.HOSPITAL_DISCHARGE, EventType.PROCEDURE,
    }
    if event.event_type in strong_types:
        score += 15

    # Content anchors — +5 each, max 15
    anchor_kinds = {FactKind.CHIEF_COMPLAINT, FactKind.ASSESSMENT, FactKind.PLAN, FactKind.IMPRESSION}
    anchor_count = sum(1 for f in event.facts if f.kind in anchor_kinds)
    score += min(anchor_count * 5, 15)

    # Fact richness — reward events with ≥3 facts
    if len(event.facts) >= 3:
        score += 5

    # Citation coverage — reward events with multiple citations
    if len(event.citation_ids) >= 2:
        score += 5

    # Multi-page events are stronger
    if len(event.source_page_numbers) > 1:
        score += 5

    return min(score, 100)


def apply_confidence_scoring(
    events: list[Event],
    config: RunConfig,
) -> tuple[list[Event], list[Warning]]:
    """
    Score all events and apply flags.
    Returns (events_with_scores, warnings).
    """
    warnings: list[Warning] = []

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
