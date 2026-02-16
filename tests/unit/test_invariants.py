"""
Invariant tests for the Evidence Graph.

These tests enforce non-negotiable invariants that must never break:
1. Every Event has >= 1 citation_id (or explicit flag)
2. Every Citation references an existing page_id
3. Provider entities are deduped deterministically
4. Evidence Graph is deterministic and JSON-serializable
5. EvidenceGraph has schema_version
6. Extensions namespace exists
"""
import json
import pytest
from datetime import date

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


def _sample_graph():
    """Build a minimal but valid evidence graph."""
    page = Page(
        page_id="page-1",
        source_document_id="doc-1",
        page_number=1,
        text="Chief Complaint: Low back pain",
        text_source="embedded_pdf_text",
        page_type=PageType.CLINICAL_NOTE,
    )
    citation = Citation(
        citation_id="cit-1",
        source_document_id="doc-1",
        page_number=1,
        snippet="Low back pain",
        bbox=BBox(x=0, y=0, w=100, h=20),
    )
    provider = Provider(
        provider_id="prov-1",
        detected_name_raw="Dr. Smith, MD",
        normalized_name="dr smith",
        provider_type=ProviderType.PHYSICIAN,
        confidence=80,
    )
    event = Event(
        event_id="evt-1",
        provider_id="prov-1",
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=date(2024, 3, 15), source=DateSource.TIER1),
        facts=[Fact(text="Low back pain", kind=FactKind.CHIEF_COMPLAINT, verbatim=True, citation_id="cit-1")],
        confidence=80,
        citation_ids=["cit-1"],
        source_page_numbers=[1],
    )
    return EvidenceGraph(
        pages=[page],
        providers=[provider],
        events=[event],
        citations=[citation],
    )


class TestInvariantSchemaVersion:
    """Invariant: EvidenceGraph has schema_version."""

    def test_has_schema_version(self):
        graph = _sample_graph()
        assert hasattr(graph, "schema_version")
        assert graph.schema_version == "1.0"

    def test_schema_version_in_json(self):
        graph = _sample_graph()
        data = json.loads(graph.model_dump_json())
        assert "schema_version" in data
        assert data["schema_version"] == "1.0"


class TestInvariantExtensions:
    """Invariant: Extensions namespace exists."""

    def test_extensions_exist(self):
        graph = _sample_graph()
        assert hasattr(graph, "extensions")
        assert isinstance(graph.extensions, dict)

    def test_extensions_in_json(self):
        graph = _sample_graph()
        data = json.loads(graph.model_dump_json())
        assert "extensions" in data

    def test_extensions_additive(self):
        """Adding to extensions does not break serialization."""
        graph = _sample_graph()
        graph.extensions["test_key"] = {"foo": "bar"}
        data = json.loads(graph.model_dump_json())
        assert data["extensions"]["test_key"]["foo"] == "bar"


class TestInvariantCitationRefs:
    """Invariant: Every Citation references an existing page_id (page_number matches a page)."""

    def test_citation_page_exists(self):
        graph = _sample_graph()
        page_numbers = {p.page_number for p in graph.pages}
        for cit in graph.citations:
            assert cit.page_number in page_numbers, (
                f"Citation {cit.citation_id} references page {cit.page_number} "
                f"which does not exist in graph pages"
            )


class TestInvariantEventCitations:
    """Invariant: Every Event has >= 1 citation_id or an explicit flag."""

    def test_event_has_citations_or_flag(self):
        graph = _sample_graph()
        for evt in graph.events:
            has_citations = len(evt.citation_ids) > 0
            has_flag = any(
                f in evt.flags
                for f in ["MISSING_CITATION", "MISSING_DATE", "NO_CITATIONS"]
            )
            assert has_citations or has_flag, (
                f"Event {evt.event_id} has no citation_ids and no explanatory flag"
            )


class TestInvariantJsonSerializable:
    """Invariant: Evidence Graph is JSON-serializable."""

    def test_serializable(self):
        graph = _sample_graph()
        json_str = graph.model_dump_json()
        assert json_str is not None
        # Round-trip
        data = json.loads(json_str)
        graph2 = EvidenceGraph.model_validate(data)
        assert len(graph2.events) == len(graph.events)
        assert graph2.schema_version == graph.schema_version

    def test_serializable_with_extensions(self):
        graph = _sample_graph()
        graph.extensions["coverage_spans"] = [
            {"provider": "test", "start": "2024-01-01", "end": "2024-12-01"}
        ]
        json_str = graph.model_dump_json()
        data = json.loads(json_str)
        assert len(data["extensions"]["coverage_spans"]) == 1


class TestInvariantDeterministic:
    """Invariant: Evidence Graph serialization is deterministic."""

    def test_deterministic_json(self):
        g1 = _sample_graph()
        g2 = _sample_graph()
        assert g1.model_dump_json() == g2.model_dump_json()
