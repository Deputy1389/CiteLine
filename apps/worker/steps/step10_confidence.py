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
    if event.date.source == DateSource.TIER1:
        score += 40
    elif event.date.source == DateSource.TIER2:
        score += 25

    # Provider confidence (approximation)
    if event.provider_id and event.provider_id != "unknown":
        score += 30  # Assume tier1 if identified
    else:
        score += 5

    # Encounter type strong cue
    strong_types = {
        EventType.ER_VISIT, EventType.HOSPITAL_ADMISSION,
        EventType.HOSPITAL_DISCHARGE, EventType.PROCEDURE,
    }
    if event.event_type in strong_types:
        score += 20

    # Content anchor present
    anchor_kinds = {FactKind.CHIEF_COMPLAINT, FactKind.ASSESSMENT, FactKind.PLAN, FactKind.IMPRESSION}
    if any(f.kind in anchor_kinds for f in event.facts):
        score += 10

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
