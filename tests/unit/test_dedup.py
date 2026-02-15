"""
Unit tests for deduplication (Step 9).
"""
import pytest
from packages.shared.models import (
    DateKind, DateSource, Event, EventDate, EventType, Fact, FactKind,
)
from apps.worker.steps.step09_dedup import deduplicate_events
from datetime import date


def _make_event(
    provider_id: str = "prov1",
    event_type: EventType = EventType.OFFICE_VISIT,
    event_date: date = date(2024, 3, 15),
    page_numbers: list[int] | None = None,
    facts_text: list[str] | None = None,
) -> Event:
    pages = page_numbers or [1]
    texts = facts_text or ["Test fact"]
    return Event(
        event_id=f"evt-{id(texts)}",
        provider_id=provider_id,
        event_type=event_type,
        date=EventDate(kind=DateKind.SINGLE, value=event_date, source=DateSource.TIER1),
        facts=[Fact(text=t, kind=FactKind.OTHER, verbatim=False, citation_id="cit1") for t in texts],
        confidence=70,
        citation_ids=["cit1"],
        source_page_numbers=pages,
    )


class TestDeduplication:
    def test_no_duplicates(self):
        events = [
            _make_event(event_date=date(2024, 3, 15)),
            _make_event(event_date=date(2024, 3, 20)),
        ]
        result, warnings = deduplicate_events(events)
        assert len(result) == 2

    def test_merge_same_provider_type_date(self):
        events = [
            _make_event(page_numbers=[1], facts_text=["Fact A"]),
            _make_event(page_numbers=[2], facts_text=["Fact B"]),
        ]
        result, warnings = deduplicate_events(events)
        assert len(result) == 1
        assert len(result[0].facts) == 2

    def test_no_merge_different_providers(self):
        events = [
            _make_event(provider_id="prov1"),
            _make_event(provider_id="prov2"),
        ]
        result, _ = deduplicate_events(events)
        assert len(result) == 2

    def test_no_merge_different_types(self):
        events = [
            _make_event(event_type=EventType.OFFICE_VISIT),
            _make_event(event_type=EventType.ER_VISIT),
        ]
        result, _ = deduplicate_events(events)
        assert len(result) == 2

    def test_fact_cap_at_10(self):
        events = [
            _make_event(facts_text=[f"Fact {i}" for i in range(8)]),
            _make_event(facts_text=[f"Fact {i+8}" for i in range(8)]),
        ]
        result, _ = deduplicate_events(events)
        assert len(result) == 1
        assert len(result[0].facts) <= 10

    def test_empty_list(self):
        result, _ = deduplicate_events([])
        assert result == []
