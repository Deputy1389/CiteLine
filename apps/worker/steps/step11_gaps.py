"""
Step 11 — Chronology ordering + gap detection.
Sort events by date and detect treatment gaps.
"""
from __future__ import annotations

import uuid
from datetime import date

from packages.shared.models import Event, EventType, Gap, RunConfig, Warning


def detect_gaps(
    events: list[Event],
    config: RunConfig,
) -> tuple[list[Event], list[Gap], list[Warning]]:
    """
    Sort events by date and detect gaps between adjacent non-billing events.
    Returns (sorted_events, gaps, warnings).
    """
    warnings: list[Warning] = []

    def has_full_date(e: Event):
        if not e.date or e.date.value is None:
            return False
        # If it's already a date or DateRange object, it's a full date
        from packages.shared.models import DateRange
        return isinstance(e.date.value, (date, DateRange))

    # Sort events by date using the robust sort_key
    sorted_events = sorted(events, key=lambda e: e.date.sort_key() if e.date else (99, "UNKNOWN"))

    # Filter to non-billing for gap detection AND only events with actual resolved dates (no partials)
    # ALSO exclude historical references
    dated_events = [
        e for e in sorted_events 
        if e.event_type not in (EventType.BILLING_EVENT, EventType.REFERENCED_PRIOR_EVENT) 
        and "is_reference" not in (e.flags or [])
        and has_full_date(e)
    ]

    # If not enough real dates, do not emit gaps
    if len(dated_events) < 2:
        return sorted_events, [], warnings

    gaps: list[Gap] = []
    base_threshold = max(config.gap_threshold_days, 120)
    short_gap_anchor_types = {EventType.HOSPITAL_ADMISSION, EventType.PROCEDURE}

    for i in range(1, len(dated_events)):
        prev_date = dated_events[i - 1].date.value
        curr_date = dated_events[i].date.value
        
        # Guard against DateRange (take start)
        if hasattr(prev_date, "start"): prev_date = prev_date.start
        if hasattr(curr_date, "start"): curr_date = curr_date.start

        if not isinstance(prev_date, date) or not isinstance(curr_date, date):
            continue
            
        delta_days = (curr_date - prev_date).days

        # FIXED: Special handling for inpatient daily notes - 
        # Treat them as same-day if within the same admission context (simulated by <1 day delta)
        if delta_days == 0:
            continue

        prev_evt = dated_events[i - 1]
        next_evt = dated_events[i]
        prev_blob = " ".join((f.text or "") for f in prev_evt.facts).lower()
        next_blob = " ".join((f.text or "") for f in next_evt.facts).lower()
        post_acute = (
            prev_evt.event_type in short_gap_anchor_types
            or next_evt.event_type in short_gap_anchor_types
            or ("hospice" in prev_blob or "hospice" in next_blob)
            or ("skilled nursing" in prev_blob or "skilled nursing" in next_blob or "snf" in prev_blob or "snf" in next_blob)
        )
        pair_threshold = 90 if post_acute else base_threshold
        if delta_days >= pair_threshold:
            gaps.append(Gap(
                gap_id=uuid.uuid4().hex[:16],
                start_date=prev_date,
                end_date=curr_date,
                duration_days=delta_days,
                threshold_days=pair_threshold,
                confidence=80,
                related_event_ids=[
                    dated_events[i - 1].event_id,
                    dated_events[i].event_id,
                ],
            ))

    return sorted_events, gaps, warnings
