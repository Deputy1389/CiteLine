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

    # Sort events by date (guarded against None date)
    sorted_events = sorted(events, key=lambda e: e.date.sort_date() if e.date else date.min)

    # Filter to non-billing for gap detection
    non_billing = [e for e in sorted_events if e.event_type != EventType.BILLING_EVENT]

    gaps: list[Gap] = []
    threshold = config.gap_threshold_days

    for i in range(1, len(non_billing)):
        # Guard against potentially missing dates even after sorting
        if not non_billing[i-1].date or not non_billing[i].date:
            continue

        prev_date = non_billing[i - 1].date.sort_date()
        curr_date = non_billing[i].date.sort_date()
        
        # FIXED: Enforce minimum year to prevent impossible gaps (e.g. 1897)
        if prev_date.year < 1990 or curr_date.year < 1990:
            continue
            
        delta_days = (curr_date - prev_date).days

        # FIXED: Special handling for inpatient daily notes - 
        # Treat them as same-day if within the same admission context (simulated by <1 day delta)
        if delta_days == 0:
            continue

        if delta_days >= threshold:
            gaps.append(Gap(
                gap_id=uuid.uuid4().hex[:16],
                start_date=prev_date,
                end_date=curr_date,
                duration_days=delta_days,
                threshold_days=threshold,
                confidence=80,
                related_event_ids=[
                    non_billing[i - 1].event_id,
                    non_billing[i].event_id,
                ],
            ))

    return sorted_events, gaps, warnings
