from datetime import date

from apps.worker.lib.pt_enumeration import build_pt_evidence_extensions
from packages.shared.models import BBox, Citation, DateKind, DateSource, EventDate, Page, PageType, Provider, ProviderType


def _page(page_no: int, text: str, page_type: PageType) -> Page:
    return Page(
        page_id=f"p-{page_no}",
        source_document_id="doc-1",
        page_number=page_no,
        text=text,
        text_source="ocr",
        page_type=page_type,
    )


def _cit(page_no: int, cid: str, snippet: str) -> Citation:
    return Citation(
        citation_id=cid,
        source_document_id="doc-1",
        page_number=page_no,
        snippet=snippet,
        bbox=BBox(x=1, y=1, w=1, h=1),
    )


def _dt(d: date) -> EventDate:
    return EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1)


def _provider() -> Provider:
    return Provider(
        provider_id="prov-pt",
        detected_name_raw="Elite Physical Therapy",
        normalized_name="Elite Physical Therapy",
        provider_type=ProviderType.PT,
        confidence=90,
    )


def test_extracts_dated_pt_encounters_from_pt_note_pages() -> None:
    pages = [
        _page(10, "Physical Therapy\nDate of Service: 11/19/2024\nSubjective: neck pain\nObjective: ROM limited\nTherapeutic Exercise performed", PageType.PT_NOTE),
        _page(11, "PT Daily Note\nDate: 11/21/2024\nAssessment: improving\nPlan: continue therapy", PageType.PT_NOTE),
    ]
    dates = {10: [_dt(date(2024, 11, 19))], 11: [_dt(date(2024, 11, 21))]}
    citations = [
        _cit(10, "c10", "Physical Therapy DOS 11/19/2024"),
        _cit(11, "c11", "PT Daily Note DOS 11/21/2024"),
    ]
    ext = build_pt_evidence_extensions(
        pages=pages,
        dates_by_page=dates,
        providers=[_provider()],
        page_provider_map={10: "prov-pt", 11: "prov-pt"},
        citations=citations,
    )
    rows = ext["pt_encounters"]
    assert len(rows) == 2
    assert [r["encounter_date"] for r in rows] == ["2024-11-19", "2024-11-21"]
    assert all(r["source"] == "primary" for r in rows)
    assert all(r["evidence_citation_ids"] for r in rows)


def test_ignores_total_visits_summary_as_primary_evidence() -> None:
    pages = [
        _page(12, "Physical Therapy Discharge Summary\nTotal PT visits: 141\nDischarge pain score 2/10", PageType.DISCHARGE_SUMMARY),
    ]
    dates = {12: [_dt(date(2025, 11, 16))]}
    citations = [_cit(12, "c12", "Physical Therapy Discharge Summary Total PT visits: 141")]
    ext = build_pt_evidence_extensions(
        pages=pages,
        dates_by_page=dates,
        providers=[_provider()],
        page_provider_map={12: "prov-pt"},
        citations=citations,
    )
    assert ext["pt_encounters"] == []
    reported = ext["pt_count_reported"]
    assert reported and reported[0]["reported_count"] == 141
    assert ext["pt_reconciliation"]["verified_pt_count"] == 0
    assert ext["pt_reconciliation"]["reported_pt_count_max"] == 141


def test_reconciliation_flags_variance_when_reported_exceeds_verified() -> None:
    pages = [
        _page(20, "Physical Therapy\nDate: 11/19/2024\nObjective ROM\nTherapeutic Exercise", PageType.PT_NOTE),
        _page(21, "PT Progress Summary\nTotal PT visits: 12", PageType.PT_NOTE),
    ]
    dates = {20: [_dt(date(2024, 11, 19))], 21: [_dt(date(2024, 11, 26))]}
    citations = [_cit(20, "c20", "PT visit 11/19/2024"), _cit(21, "c21", "PT Progress Summary Total PT visits: 12")]
    ext = build_pt_evidence_extensions(
        pages=pages,
        dates_by_page=dates,
        providers=[_provider()],
        page_provider_map={20: "prov-pt", 21: "prov-pt"},
        citations=citations,
    )
    # page 21 is summary-only and should not increment verified
    assert ext["pt_reconciliation"]["verified_pt_count"] == 1
    assert ext["pt_reconciliation"]["reported_pt_count_max"] == 12
    assert ext["pt_reconciliation"]["variance_flag"] is True
    assert ext["pt_reconciliation"]["severe_variance_flag"] is True
