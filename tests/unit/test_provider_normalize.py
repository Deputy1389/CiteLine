"""
Unit tests for provider normalization and coverage spans (Phase 1).
"""
import pytest
from datetime import date

from apps.worker.lib.provider_normalize import (
    normalize_provider_name,
    normalize_provider_entities,
    compute_coverage_spans,
)
from packages.shared.models import (
    BBox,
    Citation,
    DateKind,
    DateSource,
    EvidenceGraph,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Page,
    PageType,
    Provider,
    ProviderEvidence,
    ProviderType,
)


# ── normalize_provider_name ──────────────────────────────────────────────


class TestNormalizeProviderName:
    """Test credential stripping and normalization."""

    def test_strip_md(self):
        assert normalize_provider_name("John Smith, MD") == "john smith"

    def test_strip_do(self):
        assert normalize_provider_name("Jane Doe, DO") == "jane doe"

    def test_strip_pac(self):
        assert normalize_provider_name("Bob Jones, PA-C") == "bob jones"

    def test_strip_dpt(self):
        assert normalize_provider_name("Alice Brown, DPT") == "alice brown"

    def test_strip_multiple_suffixes(self):
        result = normalize_provider_name("Dr. Smith, MD, PA")
        assert "md" not in result
        assert "pa" not in result

    def test_casefold(self):
        assert normalize_provider_name("JOHNS HOPKINS HOSPITAL") == "johns hopkins hospital"

    def test_collapse_whitespace(self):
        assert normalize_provider_name("  John   Smith  ") == "john smith"

    def test_strip_llc(self):
        assert normalize_provider_name("Acme Health LLC") == "acme health"

    def test_standardize_saint(self):
        assert "st" in normalize_provider_name("Saint Mary's Hospital")

    def test_standardize_center(self):
        assert "ctr" in normalize_provider_name("Health Center of Texas")

    def test_empty_string(self):
        assert normalize_provider_name("") == ""

    def test_deterministic(self):
        """Same input always produces same output."""
        name = "Dr. Robert Johnson, MD"
        assert normalize_provider_name(name) == normalize_provider_name(name)

    def test_strip_medical_group(self):
        result = normalize_provider_name("Pacific Medical Group")
        assert "medical group" not in result


# ── normalize_provider_entities (dedupe) ─────────────────────────────────


def _make_provider(pid, raw_name, ptype=ProviderType.UNKNOWN):
    return Provider(
        provider_id=pid,
        detected_name_raw=raw_name,
        normalized_name=raw_name.lower(),
        provider_type=ptype,
        confidence=80,
        evidence=[ProviderEvidence(
            page_number=1,
            snippet=raw_name[:260],
            bbox=BBox(x=0, y=0, w=0, h=0),
        )],
    )


def _make_event(eid, pid, d=None, cit_ids=None):
    return Event(
        event_id=eid,
        provider_id=pid,
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1) if d else None,
        facts=[Fact(text="test", kind=FactKind.CHIEF_COMPLAINT, verbatim=True, citation_id="c1")],
        confidence=80,
        flags=[] if d else ["MISSING_DATE"],
        citation_ids=cit_ids or ["c1"],
        source_page_numbers=[1],
    )


class TestNormalizeProviderEntities:
    """Test deterministic provider deduplication."""

    def test_merges_same_name(self):
        """Two providers with same normalized name should merge."""
        graph = EvidenceGraph(
            providers=[
                _make_provider("p1", "John Smith, MD"),
                _make_provider("p2", "John Smith MD"),
            ],
            events=[
                _make_event("e1", "p1", date(2024, 1, 1)),
                _make_event("e2", "p2", date(2024, 6, 1)),
            ],
        )
        entities = normalize_provider_entities(graph)
        # Should merge into one entity
        assert len(entities) == 1
        assert entities[0]["event_count"] == 2
        assert entities[0]["first_seen_date"] == "2024-01-01"
        assert entities[0]["last_seen_date"] == "2024-06-01"

    def test_different_names_not_merged(self):
        """Different providers should not merge."""
        graph = EvidenceGraph(
            providers=[
                _make_provider("p1", "John Smith, MD"),
                _make_provider("p2", "Jane Doe, DO"),
            ],
            events=[],
        )
        entities = normalize_provider_entities(graph)
        assert len(entities) == 2

    def test_keeps_best_display_name(self):
        """Should keep the longer (more descriptive) raw name as display."""
        graph = EvidenceGraph(
            providers=[
                _make_provider("p1", "John Smith"),
                _make_provider("p2", "John Smith, MD, DO"),
            ],
            events=[],
        )
        entities = normalize_provider_entities(graph)
        assert len(entities) == 1
        # Longer name preferred
        assert entities[0]["display_name"] == "John Smith, MD, DO"

    def test_citation_count_aggregated(self):
        """Citation counts should aggregate across merged providers."""
        graph = EvidenceGraph(
            providers=[
                _make_provider("p1", "Dr Smith MD"),
                _make_provider("p2", "Dr Smith, MD"),
            ],
            events=[
                _make_event("e1", "p1", date(2024, 1, 1), ["c1", "c2"]),
                _make_event("e2", "p2", date(2024, 2, 1), ["c3"]),
            ],
        )
        entities = normalize_provider_entities(graph)
        assert len(entities) == 1
        assert entities[0]["citation_count"] == 3

    def test_dateless_events_counted(self):
        """Events without dates should still count."""
        graph = EvidenceGraph(
            providers=[_make_provider("p1", "Dr Smith")],
            events=[
                _make_event("e1", "p1"),  # no date
                _make_event("e2", "p1"),  # no date
            ],
        )
        entities = normalize_provider_entities(graph)
        assert entities[0]["event_count"] == 2
        assert entities[0]["first_seen_date"] is None

    def test_deterministic_output(self):
        """Same graph should always produce same entity list."""
        graph = EvidenceGraph(
            providers=[
                _make_provider("p1", "Beta Clinic"),
                _make_provider("p2", "Alpha Hospital"),
            ],
            events=[],
        )
        r1 = normalize_provider_entities(graph)
        r2 = normalize_provider_entities(graph)
        assert r1 == r2


# ── compute_coverage_spans ───────────────────────────────────────────────


class TestCoverageSpans:
    def test_span_from_dated_entity(self):
        entities = [{
            "normalized_name": "test",
            "display_name": "Test Clinic",
            "provider_type": "clinic",
            "first_seen_date": "2024-01-01",
            "last_seen_date": "2024-12-01",
            "event_count": 5,
            "citation_count": 10,
        }]
        spans = compute_coverage_spans(entities)
        assert len(spans) == 1
        assert spans[0]["start_date"] == "2024-01-01"
        assert spans[0]["end_date"] == "2024-12-01"

    def test_no_span_for_dateless(self):
        entities = [{
            "normalized_name": "test",
            "display_name": "Test",
            "provider_type": "unknown",
            "first_seen_date": None,
            "last_seen_date": None,
            "event_count": 1,
            "citation_count": 1,
        }]
        spans = compute_coverage_spans(entities)
        assert len(spans) == 0
