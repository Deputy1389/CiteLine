from datetime import date

from apps.worker.lib.pt_enumeration import build_pt_evidence_extensions
from packages.shared.models import BBox, Citation, DateKind, DateSource, EventDate, Page, PageType, Provider, ProviderType


def _page(page_no: int, text: str, page_type: PageType, doc: str = "doc-1") -> Page:
    return Page(
        page_id=f"p-{page_no}",
        source_document_id=doc,
        page_number=page_no,
        text=text,
        text_source="ocr",
        page_type=page_type,
    )


def _cit(page_no: int, cid: str, snippet: str, doc: str = "doc-1") -> Citation:
    return Citation(
        citation_id=cid,
        source_document_id=doc,
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
    assert all("elite physical therapy" in str(r["facility_name"]).lower() for r in rows)


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


def test_clinical_note_ed_flowsheet_does_not_create_pt_encounter() -> None:
    pages = [
        _page(
            31,
            "ED Clinical Note\nDate: 10/11/2024\nPT Request received\n15:10 Rounded on patient\n15:45 Toileting assistance\n16:20 RN note",
            PageType.CLINICAL_NOTE,
        )
    ]
    dates = {31: [_dt(date(2024, 10, 11))]}
    citations = [_cit(31, "c31", "ED nursing flowsheet with PT Request")]
    ext = build_pt_evidence_extensions(
        pages=pages,
        dates_by_page=dates,
        providers=[_provider()],
        page_provider_map={31: "prov-pt"},
        citations=citations,
    )
    assert ext["pt_encounters"] == []


def test_same_day_pt_note_pages_dedupe_to_single_encounter_same_document() -> None:
    pages = [
        _page(40, "Physical Therapy\nDate: 11/19/2024\nPlan of Care\nTherapeutic Exercise\nHEP", PageType.PT_NOTE),
        _page(41, "Physical Therapy\nDate: 11/19/2024\nPlan of Care continued\nManual Therapy\nHEP", PageType.PT_NOTE),
    ]
    dates = {40: [_dt(date(2024, 11, 19))], 41: [_dt(date(2024, 11, 19))]}
    citations = [_cit(40, "c40", "PT note page 1"), _cit(41, "c41", "PT note page 2")]
    ext = build_pt_evidence_extensions(
        pages=pages,
        dates_by_page=dates,
        providers=[_provider()],
        page_provider_map={40: "prov-pt", 41: "prov-pt"},
        citations=citations,
    )
    rows = ext["pt_encounters"]
    assert len(rows) == 1
    assert rows[0]["dedupe_pages_count"] == 2
    assert sorted(rows[0]["contributing_page_numbers"]) == [40, 41]
    assert set(rows[0]["evidence_citation_ids"]) == {"c40", "c41"}


def test_pt_date_concentration_anomaly_triggers() -> None:
    pages = []
    dates = {}
    citations = []
    # 5 on one date, 3 on other dates => 8 total, anomaly should trigger
    for idx, (pg, ds, doc_id, clinic_name) in enumerate([
        (50, date(2024, 11, 19), "doc-a", "Alpha Physical Therapy"),
        (51, date(2024, 11, 19), "doc-b", "Bravo Physical Therapy"),
        (52, date(2024, 11, 19), "doc-c", "Charlie Physical Therapy"),
        (53, date(2024, 11, 19), "doc-d", "Delta Physical Therapy"),
        (54, date(2024, 11, 19), "doc-e", "Echo Physical Therapy"),
        (55, date(2024, 11, 21), "doc-f", "Foxtrot Physical Therapy"),
        (56, date(2024, 11, 23), "doc-g", "Golf Physical Therapy"),
        (57, date(2024, 11, 25), "doc-h", "Hotel Physical Therapy"),
    ]):
        pages.append(_page(pg, f"{clinic_name}\nDate: {ds.month}/{ds.day}/{ds.year}\nPlan of Care\nHEP\nTherapeutic Exercise", PageType.PT_NOTE, doc=doc_id))
        dates[pg] = [_dt(ds)]
        citations.append(_cit(pg, f"c{pg}", f"PT note {idx}", doc=doc_id))
    ext = build_pt_evidence_extensions(
        pages=pages,
        dates_by_page=dates,
        providers=[],
        page_provider_map={},
        citations=citations,
    )
    an = ext["pt_reconciliation"]["date_concentration_anomaly"]
    assert ext["pt_reconciliation"]["verified_pt_count"] == 8
    assert an["triggered"] is True
    assert an["max_date_count"] == 5
    assert an["max_date"] == "2024-11-19"
