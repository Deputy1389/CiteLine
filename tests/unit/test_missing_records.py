"""
Unit tests for missing record detection (Phase 3).
"""
import pytest
from datetime import date

from apps.worker.steps.step15_missing_records import (
    detect_missing_records,
)
from packages.shared.models import (
    DateKind,
    DateSource,
    EvidenceGraph,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Provider,
    ProviderType,
)


def _evt(eid, d=None, pid="p1", cit_ids=None, pages=None):
    return Event(
        event_id=eid,
        provider_id=pid,
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1) if d else None,
        facts=[Fact(text="test", kind=FactKind.CHIEF_COMPLAINT, verbatim=True, citation_id="c1")],
        confidence=80,
        flags=[] if d else ["MISSING_DATE"],
        citation_ids=cit_ids or ["c1"],
        source_page_numbers=pages or [1],
    )


class TestMissingRecords:
    def test_global_gap_detected(self):
        # Global gap threshold is 45 days for medium, 90 for high
        graph = EvidenceGraph(events=[
            _evt("e1", date(2024, 1, 1), pid="p1"),
            _evt("e2", date(2024, 3, 1), pid="p2"), # 60 days gap
        ])
        result = detect_missing_records(graph, [])
        gaps = result["gaps"]
        
        # Should have 1 global gap (60 days)
        global_gaps = [g for g in gaps if g["rule_name"] == "global_gap"]
        assert len(global_gaps) == 1
        assert global_gaps[0]["gap_days"] == 60
        assert global_gaps[0]["severity"] == "medium"

    def test_global_gap_high_severity(self):
        graph = EvidenceGraph(events=[
            _evt("e1", date(2024, 1, 1), pid="p1"),
            _evt("e2", date(2024, 5, 1), pid="p2"), # ~121 days gap
        ])
        result = detect_missing_records(graph, [])
        global_gaps = [g for g in result["gaps"] if g["rule_name"] == "global_gap"]
        assert len(global_gaps) == 1
        assert global_gaps[0]["severity"] == "high"

    def test_provider_gap_detected(self):
        # Provider gap threshold is 30 days for medium, 60 for high
        graph = EvidenceGraph(
            providers=[Provider(
                provider_id="p1",
                detected_name_raw="Dr. Smith",
                normalized_name="dr smith",
                provider_type=ProviderType.PHYSICIAN,
                confidence=80,
            )],
            events=[
                _evt("e1", date(2024, 1, 1), pid="p1"),
                _evt("e2", date(2024, 2, 15), pid="p1"), # 45 days gap
            ],
        )
        result = detect_missing_records(graph, [])
        provider_gaps = [g for g in result["gaps"] if g["rule_name"] == "provider_gap"]
        assert len(provider_gaps) == 1
        assert provider_gaps[0]["provider_id"] == "p1"
        assert provider_gaps[0]["gap_days"] == 45
        assert provider_gaps[0]["severity"] == "medium"

    def test_provider_gap_high_severity(self):
        graph = EvidenceGraph(
            providers=[Provider(
                provider_id="p1",
                detected_name_raw="Dr. Smith",
                normalized_name="dr smith",
                provider_type=ProviderType.PHYSICIAN,
                confidence=80,
            )],
            events=[
                _evt("e1", date(2024, 1, 1), pid="p1"),
                _evt("e2", date(2024, 4, 1), pid="p1"), # 91 days gap
            ],
        )
        result = detect_missing_records(graph, [])
        provider_gaps = [g for g in result["gaps"] if g["rule_name"] == "provider_gap"]
        assert len(provider_gaps) == 1
        assert provider_gaps[0]["severity"] == "high"

    def test_no_gaps_below_threshold(self):
        graph = EvidenceGraph(
            providers=[Provider(
                provider_id="p1",
                detected_name_raw="Dr. Smith",
                normalized_name="dr smith",
                provider_type=ProviderType.PHYSICIAN,
                confidence=80,
            )],
            events=[
                _evt("e1", date(2024, 1, 1), pid="p1"),
                _evt("e2", date(2024, 1, 20), pid="p1"), # 19 days gap
            ],
        )
        result = detect_missing_records(graph, [])
        assert len(result["gaps"]) == 0

    def test_suggested_records_to_request(self):
        graph = EvidenceGraph(events=[
            _evt("e1", date(2024, 1, 1), pid="p1"),
            _evt("e2", date(2024, 3, 1), pid="p1"),
        ])
        result = detect_missing_records(graph, [])
        gap = result["gaps"][0] # Could be provider or global depending on implementation, 
                                # but both should have suggested_records_to_request
        assert "suggested_records_to_request" in gap
        sreq = gap["suggested_records_to_request"]
        assert sreq["from"] == "2024-01-02"
        assert sreq["to"] == "2024-02-29"

    def test_summary_metrics(self):
        graph = EvidenceGraph(events=[
            _evt("e1", date(2024, 1, 1), pid="p1"),
            _evt("e2", date(2024, 5, 1), pid="p1"), # High severity both
        ])
        result = detect_missing_records(graph, [])
        summary = result["summary"]
        assert summary["total_gaps"] == 2 # 1 provider gap + 1 global gap
        assert summary["high_severity_count"] == 2
        assert summary["medium_severity_count"] == 0

    def test_deterministic_hashes(self):
        graph = EvidenceGraph(events=[
            _evt("e1", date(2024, 1, 1), pid="p1"),
            _evt("e2", date(2024, 3, 1), pid="p1"),
        ])
        r1 = detect_missing_records(graph, [])
        r2 = detect_missing_records(graph, [])
        assert r1["gaps"][0]["gap_id"] == r2["gaps"][0]["gap_id"]
