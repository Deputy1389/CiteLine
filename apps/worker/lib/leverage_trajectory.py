"""
leverage_trajectory.py — Pass 38 / Pass 40

Deterministic Leverage Trajectory computation.

Rules:
  - Consumes CaseSignals only (escalation_events list).
  - Only dated events (is_known=True) are used — enforced upstream in derive_case_signals().
  - Uses the same InvariantGuard as compute_leverage_index().
  - Renderer must not call this directly — result is pre-computed in orchestrator.
  - Pass 40: source_anchor threaded from escalation_events into markers (INTERNAL only).
"""
from __future__ import annotations

from typing import Optional
from packages.shared.models.domain import EscalationEvent, InvariantGuard, LeverageTrajectory


# ── Policy clause map (Pass 40) ───────────────────────────────────────────────
# Maps escalation kind → LeveragePolicy parameter name.
# Used by orchestrator for INTERNAL serialization only — never stored on EscalationEvent.
_POLICY_CLAUSE_MAP: dict[str, str] = {
    "ED":            "base_none",
    "PT_START":      "bonus_pt_5to11",
    "IMAGING":       "base_imaging_pathology",
    "SPECIALIST":    "base_imaging_pathology",
    "NEURO_DEFICIT": "base_radiculopathy_or_deficit",
    "INJECTION":     "base_injection_dated",
    "SURGERY":       "base_surgery",
}


def compute_leverage_trajectory(
    signals: dict,
    guard: Optional[InvariantGuard],
) -> LeverageTrajectory:
    """Compute the Leverage Trajectory from pre-derived case signals.

    Guard validation uses the same _validate_guard() as compute_leverage_index()
    (imported from leverage_index). Stale signals or missing guard → disabled.
    """
    from apps.worker.lib.leverage_index import _validate_guard

    suppressed_undated_count = 0
    fail_reason = _validate_guard(guard, signals)
    if fail_reason:
        return LeverageTrajectory(
            enabled=False,
            guard_status=fail_reason,
            peak_level=None,
            time_to_peak_days=None,
            num_level_increases=None,
            pattern=None,
            monthly_levels=[],
            markers=[],
            coverage_ratio=None,
            suppressed_undated_count=suppressed_undated_count,
        )

    # INV-E2 confidence threshold (Pass 41)
    _CONFIDENCE_THRESHOLD = 0.80

    raw_events: list[dict] = list(signals.get("escalation_events") or [])
    dated_events: list[dict] = []
    for ev in raw_events:
        if ev.get("date"):
            dated_events.append(ev)
        else:
            suppressed_undated_count += 1
    raw_events = dated_events

    if not raw_events:
        return LeverageTrajectory(
            enabled=True,
            guard_status="PASS",
            peak_level=None,
            time_to_peak_days=None,
            num_level_increases=None,
            pattern=None,
            monthly_levels=[],
            markers=[],
            coverage_ratio=None,
            suppressed_undated_count=suppressed_undated_count,
        )

    # INV-E2 (Pass 41, Option B): filter out low-confidence events before
    # contributing to peak_level, monthly_levels, or markers.
    # Pre-Pass-41 events without confidence key default to 0.90 (full trust).
    suppressed_low_confidence_count = 0
    filtered_events: list[dict] = []
    for ev in raw_events:
        ev_confidence = float(ev.get("confidence", 0.90))
        if ev_confidence < _CONFIDENCE_THRESHOLD:
            suppressed_low_confidence_count += 1
        else:
            filtered_events.append(ev)
    raw_events = filtered_events

    # Sort by date
    sorted_events = sorted(raw_events, key=lambda e: e["date"])

    # Build monthly max level step function
    from datetime import date as _date, timedelta as _td
    from collections import defaultdict

    monthly: dict[str, int] = defaultdict(int)
    markers: list[EscalationEvent] = []
    first_date: _date | None = None
    peak_event_date: _date | None = None
    peak_level = 0
    prev_level = 0
    num_level_increases = 0

    for ev in sorted_events:
        try:
            d = _date.fromisoformat(ev["date"])
        except Exception:
            continue
        if first_date is None:
            first_date = d
        month_key = f"{d.year:04d}-{d.month:02d}"
        level = int(ev.get("level", 0))
        if level > monthly[month_key]:
            monthly[month_key] = level
        _kind = str(ev.get("kind", ""))
        if level > peak_level:
            peak_level = level
            peak_event_date = d
            markers.append(EscalationEvent(
                date=ev["date"],
                level=level,
                kind=_kind,
                source_anchor=ev.get("source_anchor"),
            ))
        elif level > prev_level:
            markers.append(EscalationEvent(
                date=ev["date"],
                level=level,
                kind=_kind,
                source_anchor=ev.get("source_anchor"),
            ))
        if level > prev_level:
            num_level_increases += 1
        prev_level = max(prev_level, level)

    # Forward-fill monthly step function
    if monthly and first_date and peak_event_date:
        all_months: list[str] = []
        cur = _date(first_date.year, first_date.month, 1)
        end_date = peak_event_date
        end = _date(end_date.year, end_date.month, 1)
        last_level = 0
        while cur <= end:
            mk = f"{cur.year:04d}-{cur.month:02d}"
            if mk in monthly:
                last_level = monthly[mk]
            else:
                monthly[mk] = last_level
            all_months.append(mk)
            # Advance month
            if cur.month == 12:
                cur = _date(cur.year + 1, 1, 1)
            else:
                cur = _date(cur.year, cur.month + 1, 1)

        monthly_levels = [(m, monthly[m]) for m in sorted(monthly.keys())]
        total_months = len(all_months) or 1
        months_with_events = sum(1 for m in all_months if monthly.get(m, 0) > 0)
        coverage_ratio = round(months_with_events / total_months, 3)
    else:
        monthly_levels = []
        coverage_ratio = None

    # Time to peak
    time_to_peak_days: int | None = None
    if first_date and peak_event_date:
        time_to_peak_days = (peak_event_date - first_date).days

    # Pattern classification
    pattern: str | None = None
    if peak_level <= 2 and num_level_increases <= 1:
        pattern = "Flat"
    elif peak_level >= 3 and time_to_peak_days is not None and time_to_peak_days <= 90:
        pattern = "Rising"
    elif peak_level >= 4 and num_level_increases >= 3:
        pattern = "Stepped"
    elif peak_level >= 4 and time_to_peak_days is not None and time_to_peak_days > 180:
        pattern = "Late Escalation"

    return LeverageTrajectory(
        enabled=True,
        guard_status="PASS",
        peak_level=peak_level if peak_level > 0 else None,
        time_to_peak_days=time_to_peak_days,
        num_level_increases=num_level_increases,
        pattern=pattern,
        monthly_levels=monthly_levels,
        markers=markers[:5],
        coverage_ratio=coverage_ratio,
        suppressed_undated_count=suppressed_undated_count,
        suppressed_low_confidence_count=suppressed_low_confidence_count,
    )
