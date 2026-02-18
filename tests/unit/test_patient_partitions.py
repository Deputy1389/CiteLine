from __future__ import annotations

from datetime import date

from apps.worker.steps.step03b_patient_partitions import (
    assign_patient_scope_to_events,
    build_patient_partitions,
    enforce_event_patient_scope,
    validate_patient_scope_invariants,
)
from packages.shared.models import (
    BBox,
    Citation,
    DateKind,
    DateSource,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Page,
)


def _page(page_number: int, text: str) -> Page:
    return Page(
        page_id=f"p{page_number}",
        source_document_id="doc1",
        page_number=page_number,
        text=text,
        text_source="native",
    )


def _event(event_id: str, pages: list[int], citation_ids: list[str]) -> Event:
    return Event(
        event_id=event_id,
        provider_id=None,
        event_type=EventType.OFFICE_VISIT,
        date=EventDate(kind=DateKind.SINGLE, value=date(2022, 1, 1), source=DateSource.TIER1),
        facts=[Fact(text="follow-up visit", kind=FactKind.OTHER, verbatim=True)],
        confidence=80,
        citation_ids=citation_ids,
        source_page_numbers=pages,
        flags=[],
    )


def test_patient_partitions_cover_all_pages_and_are_deterministic():
    pages = [
        _page(1, "Patient Name: Alice Able"),
        _page(2, "Vitals and nursing notes"),
        _page(3, "Patient Name: Bob Baker"),
        _page(4, "Discharge summary"),
    ]
    payload_a, map_a = build_patient_partitions(pages)
    payload_b, map_b = build_patient_partitions(pages)

    assert payload_a == payload_b
    assert map_a == map_b
    covered = sum(part["page_count"] for part in payload_a["partitions"])
    assert covered == payload_a["total_pages"] == 4
    assert payload_a["partition_count"] == 2


def test_patient_scope_invariant_detects_cross_scope_event():
    pages = [
        _page(1, "Patient Name: Alice Able"),
        _page(2, "follow-up"),
        _page(3, "Patient Name: Bob Baker"),
        _page(4, "follow-up"),
    ]
    _, page_to_scope = build_patient_partitions(pages)
    events = [_event("e1", [2, 4], ["c1", "c2"])]
    citations = [
        Citation(
            citation_id="c1",
            source_document_id="doc1",
            page_number=2,
            snippet="alice note",
            bbox=BBox(x=0, y=0, w=1, h=1),
        ),
        Citation(
            citation_id="c2",
            source_document_id="doc1",
            page_number=4,
            snippet="bob note",
            bbox=BBox(x=0, y=0, w=1, h=1),
        ),
    ]
    assign_patient_scope_to_events(events, page_to_scope)
    violations = validate_patient_scope_invariants(events, citations, page_to_scope)
    assert any(v["type"] == "event_cross_scope_pages" for v in violations)


def test_enforce_event_patient_scope_removes_cross_scope_pages_and_citations():
    pages = [
        _page(1, "Patient Name: Alice Able"),
        _page(2, "follow-up"),
        _page(3, "Patient Name: Bob Baker"),
        _page(4, "follow-up"),
    ]
    _, page_to_scope = build_patient_partitions(pages)
    events = [_event("e1", [2, 4], ["c1", "c2"])]
    citations = [
        Citation(
            citation_id="c1",
            source_document_id="doc1",
            page_number=2,
            snippet="alice note",
            bbox=BBox(x=0, y=0, w=1, h=1),
        ),
        Citation(
            citation_id="c2",
            source_document_id="doc1",
            page_number=4,
            snippet="bob note",
            bbox=BBox(x=0, y=0, w=1, h=1),
        ),
    ]
    assign_patient_scope_to_events(events, page_to_scope)
    enforce_event_patient_scope(events, citations, page_to_scope)
    violations = validate_patient_scope_invariants(events, citations, page_to_scope)
    assert violations == []
