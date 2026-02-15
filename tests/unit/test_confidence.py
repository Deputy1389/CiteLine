"""
Unit tests for confidence scoring (Step 10).
"""
import pytest
from datetime import date
from packages.shared.models import (
    DateKind, DateSource, Event, EventDate, EventType, Fact, FactKind, RunConfig,
)
from apps.worker.steps.step10_confidence import score_event, apply_confidence_scoring, filter_for_export


def _make_event(
    date_source: DateSource = DateSource.TIER1,
    event_type: EventType = EventType.OFFICE_VISIT,
    provider_id: str = "prov1",
    fact_kinds: list[FactKind] | None = None,
) -> Event:
    kinds = fact_kinds or [FactKind.OTHER]
    return Event(
        event_id="test-evt",
        provider_id=provider_id,
        event_type=event_type,
        date=EventDate(kind=DateKind.SINGLE, value=date(2024, 3, 15), source=date_source),
        facts=[Fact(text=f"Test {k.value}", kind=k, verbatim=False, citation_id="cit1") for k in kinds],
        confidence=0,
        citation_ids=["cit1"],
        source_page_numbers=[1],
    )


class TestConfidenceScoring:
    def test_tier1_high_confidence(self):
        event = _make_event(
            date_source=DateSource.TIER1,
            event_type=EventType.ER_VISIT,
            fact_kinds=[FactKind.CHIEF_COMPLAINT],
        )
        score = score_event(event)
        assert score >= 80  # 40 (tier1) + 30 (provider) + 20 (strong type) + 10 (anchor) = 100

    def test_tier2_lower_confidence(self):
        event = _make_event(
            date_source=DateSource.TIER2,
            event_type=EventType.OFFICE_VISIT,
            fact_kinds=[FactKind.OTHER],
        )
        score = score_event(event)
        assert score < 80  # 25 + 30 = 55

    def test_unknown_provider_low_score(self):
        event = _make_event(provider_id="unknown")
        score = score_event(event)
        assert score < score_event(_make_event(provider_id="known-prov"))

    def test_strong_encounter_type_bonus(self):
        event_er = _make_event(event_type=EventType.ER_VISIT)
        event_office = _make_event(event_type=EventType.OFFICE_VISIT)
        assert score_event(event_er) > score_event(event_office)

    def test_content_anchor_bonus(self):
        event_with = _make_event(fact_kinds=[FactKind.CHIEF_COMPLAINT])
        event_without = _make_event(fact_kinds=[FactKind.OTHER])
        assert score_event(event_with) > score_event(event_without)

    def test_score_capped_at_100(self):
        event = _make_event(
            date_source=DateSource.TIER1,
            event_type=EventType.ER_VISIT,
            fact_kinds=[FactKind.CHIEF_COMPLAINT, FactKind.ASSESSMENT, FactKind.PLAN],
        )
        assert score_event(event) <= 100


class TestExportFiltering:
    def test_exclude_low_confidence(self):
        config = RunConfig(event_confidence_min_export=60)
        events = [
            _make_event(date_source=DateSource.TIER1),  # high conf
            _make_event(date_source=DateSource.TIER2, provider_id="unknown", event_type=EventType.OFFICE_VISIT),  # low conf
        ]
        events, _ = apply_confidence_scoring(events, config)
        exported = filter_for_export(events, config)
        assert all(e.confidence >= 60 for e in exported)

    def test_include_with_flag(self):
        config = RunConfig(
            event_confidence_min_export=60,
            low_confidence_event_behavior="include_with_flag",
        )
        events = [_make_event(date_source=DateSource.TIER2, provider_id="unknown")]
        events, _ = apply_confidence_scoring(events, config)
        exported = filter_for_export(events, config)
        assert len(exported) == len(events)  # All included
