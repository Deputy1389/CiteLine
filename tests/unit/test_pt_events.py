from datetime import date

from apps.worker.steps.events.pt import _resolved_pt_group_event_date
from packages.shared.models import DateKind, DateRange, DateSource, DateStatus, EventDate


def _partial(month: int, day: int) -> EventDate:
    return EventDate(
        kind=DateKind.SINGLE,
        value=None,
        source=DateSource.TIER2,
        status=DateStatus.AMBIGUOUS,
        partial_month=month,
        partial_day=day,
        extensions={
            "partial_date": True,
            "partial_month": month,
            "partial_day": day,
            "year_missing": True,
        },
    )


def test_resolved_pt_group_event_date_uses_real_range_when_available() -> None:
    result = _resolved_pt_group_event_date(
        [
            EventDate(kind=DateKind.SINGLE, value=date(2025, 4, 1), source=DateSource.TIER2),
            EventDate(kind=DateKind.SINGLE, value=date(2025, 5, 1), source=DateSource.TIER2),
        ]
    )
    assert result is not None
    assert result.kind == DateKind.RANGE
    assert isinstance(result.value, DateRange)
    assert result.value.start == date(2025, 4, 1)
    assert result.value.end == date(2025, 5, 1)


def test_resolved_pt_group_event_date_preserves_partial_without_1900() -> None:
    result = _resolved_pt_group_event_date([_partial(2, 10), _partial(2, 11)])
    assert result is not None
    assert result.value is None
    assert result.partial_month == 2
    assert result.partial_day == 10
    assert (result.extensions or {}).get("year_missing") is True


def test_resolved_pt_group_event_date_prefers_single_real_date_over_partial() -> None:
    result = _resolved_pt_group_event_date(
        [
            _partial(2, 10),
            EventDate(kind=DateKind.SINGLE, value=date(2025, 6, 17), source=DateSource.TIER2),
        ]
    )
    assert result is not None
    assert result.kind == DateKind.SINGLE
    assert result.value == date(2025, 6, 17)
