"""
Adversarial and edge-case tests for Missing Record Detection.
"""
import pytest
from datetime import date
from apps.worker.steps.step15_missing_records import detect_missing_records
from packages.shared.models import (
    DateKind, DateSource, EvidenceGraph, Event, EventDate, EventType, 
    Fact, FactKind, Provider, ProviderType
)

def _evt(eid, d=None, pid="p1", cit_ids=None):
    return Event(
        event_id=eid,
        provider_id=pid,
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1) if d else None,
        facts=[Fact(text="Patient complained of severe nausea and vomited twice", 
                    kind=FactKind.OTHER, verbatim=False, citation_id="c1")],
        confidence=80,
        citation_ids=cit_ids if cit_ids is not None else ["c1"],
        source_page_numbers=[1],
    )

class TestAdversarialMissingRecords:
    def test_multiple_events_same_date(self):
        graph = EvidenceGraph(
            providers=[Provider(provider_id="p1", detected_name_raw="Dr. Smith", normalized_name="dr smith", confidence=100)],
            events=[
                _evt("e1", date(2024, 1, 1), pid="p1"),
                _evt("e2", date(2024, 1, 1), pid="p1"),
                _evt("e3", date(2024, 3, 1), pid="p1"),
            ]
        )
        result = detect_missing_records(graph, [])
        p_gaps = [g for g in result["gaps"] if g["rule_name"] == "provider_gap"]
        assert len(p_gaps) == 1
        assert p_gaps[0]["gap_days"] == 60

    def test_provider_single_event(self):
        graph = EvidenceGraph(
            providers=[Provider(provider_id="p1", detected_name_raw="Dr. Smith", normalized_name="dr smith", confidence=100)],
            events=[
                _evt("e1", date(2024, 1, 1), pid="p1"),
                _evt("e2", date(2024, 1, 10), pid="p2"),
            ]
        )
        result = detect_missing_records(graph, [])
        p_gaps = [g for g in result["gaps"] if g["rule_name"] == "provider_gap"]
        assert len(p_gaps) == 0

    def test_missing_provider_id(self):
        graph = EvidenceGraph(
            events=[
                _evt("e1", date(2024, 1, 1), pid=None),
                _evt("e2", date(2024, 3, 1), pid=None),
            ]
        )
        result = detect_missing_records(graph, [])
        global_gaps = [g for g in result["gaps"] if g["rule_name"] == "global_gap"]
        assert len(global_gaps) == 1
        assert global_gaps[0]["gap_days"] == 60

    def test_citation_integrity_missing_cit_ids(self):
        graph = EvidenceGraph(
            events=[
                _evt("e1", date(2024, 1, 1), pid="p1", cit_ids=[]),
                _evt("e2", date(2024, 3, 1), pid="p1", cit_ids=[]),
            ]
        )
        result = detect_missing_records(graph, [])
        assert len(result["gaps"]) > 0
        for gap in result["gaps"]:
            assert gap["evidence"]["citation_ids"] == []

    def test_sorting_stability_ties(self):
        graph = EvidenceGraph(
            providers=[
                Provider(provider_id="pa", detected_name_raw="Dr. A", normalized_name="dr a", confidence=100),
                Provider(provider_id="pb", detected_name_raw="Dr. B", normalized_name="dr b", confidence=100),
            ],
            events=[
                _evt("e1", date(2024, 1, 1), pid="pa"),
                _evt("e2", date(2024, 2, 15), pid="pa"),
                _evt("e3", date(2024, 1, 1), pid="pb"),
                _evt("e4", date(2024, 2, 15), pid="pb"),
            ]
        )
        result = detect_missing_records(graph, [])
        p_gaps = [g for g in result["gaps"] if g["rule_name"] == "provider_gap"]
        assert len(p_gaps) == 2
        assert p_gaps[0]["provider_display_name"] == "Dr. A"
        assert p_gaps[1]["provider_display_name"] == "Dr. B"
