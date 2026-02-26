from datetime import datetime, timezone
from datetime import date

import io
from pypdf import PdfReader

from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.export_render.timeline_pdf import generate_pdf_from_projection
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
)


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join([p.extract_text() or "" for p in reader.pages])


def test_pdf_order_and_snapshot_layout() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt1",
                date_display="2024-01-01",
                event_type_display="Imaging Study",
                provider_display="Provider A",
                facts=["Very partner example rate remain better letter vehicle just."],
                citation_display="records.pdf p. 2",
            ),
        ],
    )
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Test Matter",
        projection=projection,
        gaps=[],
        narrative_synthesis="Very partner example rate remain better letter vehicle just.",
        appendix_entries=projection.entries,
        raw_events=None,
        all_citations=[],
        page_map=None,
        missing_records_payload=None,
        evidence_graph_payload={},
        run_id=None,
    )
    full_text = _pdf_text(pdf_bytes)
    assert "CASE SNAPSHOT (30-SECOND READ)" in full_text
    assert "Medical Timeline (Litigation Ready)" in full_text
    assert "Imaging & Objective Findings" in full_text
    assert "Treatment Course & Compliance" in full_text
    assert "Billing / Specials" in full_text
    assert "Citation Index & Record Appendix" in full_text
    assert full_text.find("CASE SNAPSHOT (30-SECOND READ)") < full_text.find("Medical Timeline (Litigation Ready)")
    assert full_text.find("Medical Timeline (Litigation Ready)") < full_text.find("Imaging & Objective Findings")
    assert full_text.find("Imaging & Objective Findings") < full_text.find("Treatment Course & Compliance")


def test_guardrail_bans_undermining_phrase_when_disc_dx_present() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt-disc",
                date_display="2024-11-18",
                event_type_display="Imaging Study",
                provider_display="Radiology",
                facts=["Cervical MRI shows disc material extending into neural foramen at C5-C6"],
                citation_display="records.pdf p. 10",
                confidence=95,
            ),
        ],
    )
    evidence_graph_payload = {
        "extensions": {
            "claim_rows": [
                {
                    "event_id": "evt-disc",
                    "claim_type": "INJURY_DX",
                    "date": "2024-11-18",
                    "assertion": "Cervical disc displacement with radiculopathy",
                    "citations": ["p. 10"],
                    "selection_score": 90,
                }
            ]
        }
    }
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Guardrail Case",
        projection=projection,
        gaps=[],
        narrative_synthesis="No specific traumatic injuries isolated.",
        appendix_entries=projection.entries,
        raw_events=[],
        all_citations=[],
        page_map=None,
        missing_records_payload=None,
        evidence_graph_payload=evidence_graph_payload,
        run_id=None,
    )
    text = _pdf_text(pdf_bytes).lower()
    assert "no specific traumatic injuries isolated" not in text
    assert "radiculopathy" in text or "disc displacement" in text


def test_pt_encounter_count_is_shown_when_extracted() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt-pt",
                date_display="2024-10-17 to 2025-11-13",
                event_type_display="Physical Therapy Visit",
                provider_display="Elite Physical Therapy",
                facts=["PT sessions documented: 117"],
                citation_display="records.pdf p. 52",
                confidence=90,
            ),
        ],
    )
    raw_events = [
        Event(
            event_id="evt-pt",
            provider_id="prov-1",
            event_type=EventType.PT_VISIT,
            date=EventDate(kind=DateKind.RANGE, value={"start": date(2024, 10, 17), "end": date(2025, 11, 13)}, source=DateSource.TIER1),  # pydantic coerces dict to DateRange
            facts=[Fact(text="PT sessions documented: 117", kind=FactKind.OTHER, verbatim=True, citation_ids=["cit-pt"])],
            confidence=85,
            citation_ids=["cit-pt"],
            source_page_numbers=[52],
        )
    ]
    citations = [Citation(citation_id="cit-pt", source_document_id="doc-1", page_number=52, snippet="PT sessions documented: 117", bbox=BBox(x=1, y=1, w=1, h=1))]
    pdf_bytes = generate_pdf_from_projection(
        matter_title="PT Count Case",
        projection=projection,
        gaps=[],
        appendix_entries=projection.entries,
        raw_events=raw_events,
        all_citations=citations,
        page_map={52: ("packet.pdf", 52)},
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "PT visits (Verified): 117 encounters" in text


def test_billing_incomplete_avoids_misleading_total() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    specials_summary = {
        "totals": {"total_charges": "377341.00", "total_payments": None, "total_adjustments": None, "total_balance": None},
        "by_provider": [],
        "coverage": {"billing_pages_count": 7, "earliest_service_date": "2024-10-11", "latest_service_date": "2024-10-11"},
        "dedupe": {"lines_raw": 10, "lines_deduped": 5},
        "confidence": 0.53,
        "flags": ["PARTIAL_BILLING_ONLY"],
    }
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Billing Guard Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=[],
        specials_summary=specials_summary,
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "Billing extraction incomplete." in text
    assert "Not available from extracted records (incomplete billing extraction)" in text


def test_renderer_manifest_suppresses_sentinel_doi_display() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    pdf_bytes = generate_pdf_from_projection(
        matter_title="DOI Guard Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=[],
        renderer_manifest={"doi": {"value": "1900-01-01", "source": "inferred", "citation_ids": []}},
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    pre_appendix = text.split("Citation Index & Record Appendix")[0]
    assert "1900-01-01" not in pre_appendix
    assert "Not clearly extracted from packet" in text


def test_timeline_omits_uncited_rows() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt-good",
                date_display="2024-01-02",
                event_type_display="Office Visit",
                provider_display="Clinic",
                facts=["Objective weakness 4/5 documented"],
                citation_display="records.pdf p. 5",
            ),
            ChronologyProjectionEntry(
                event_id="evt-bad",
                date_display="2024-01-03",
                event_type_display="Office Visit",
                provider_display="Clinic",
                facts=["Unsupported row should be omitted"],
                citation_display="Citation(s): Not available",
            ),
        ],
    )
    citations = [Citation(citation_id="cit-1", source_document_id="doc-1", page_number=5, snippet="Objective weakness 4/5", bbox=BBox(x=1, y=1, w=1, h=1))]
    raw_events = [
        Event(
            event_id="evt-good",
            provider_id="prov-1",
            event_type=EventType.OFFICE_VISIT,
            facts=[Fact(text="Objective weakness 4/5 documented", kind=FactKind.OTHER, verbatim=True, citation_ids=["cit-1"])],
            confidence=80,
            citation_ids=["cit-1"],
        )
    ]
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Timeline Citation Case",
        projection=projection,
        gaps=[],
        appendix_entries=projection.entries,
        raw_events=raw_events,
        all_citations=citations,
        page_map={5: ("records.pdf", 5)},
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "weakness 4/5" in text.lower()
    assert "Unsupported row should be omitted" not in text


def test_timeline_suppresses_sentinel_date_display() -> None:
    projection = ChronologyProjection(
        generated_at=datetime.now(timezone.utc),
        entries=[
            ChronologyProjectionEntry(
                event_id="evt-sentinel",
                date_display="1900-01-01 (time not documented)",
                event_type_display="Office Visit",
                provider_display="Clinic",
                facts=["Objective weakness 4/5 documented"],
                citation_display="records.pdf p. 5",
            ),
        ],
    )
    citations = [Citation(citation_id="cit-1", source_document_id="doc-1", page_number=5, snippet="Objective weakness 4/5", bbox=BBox(x=1, y=1, w=1, h=1))]
    raw_events = [
        Event(
            event_id="evt-sentinel",
            provider_id="prov-1",
            event_type=EventType.OFFICE_VISIT,
            facts=[Fact(text="Objective weakness 4/5 documented", kind=FactKind.OTHER, verbatim=True, citation_ids=["cit-1"])],
            confidence=80,
            citation_ids=["cit-1"],
        )
    ]
    pdf_bytes = generate_pdf_from_projection(
        matter_title="Sentinel Date Case",
        projection=projection,
        gaps=[],
        appendix_entries=projection.entries,
        raw_events=raw_events,
        all_citations=citations,
        page_map={5: ("records.pdf", 5)},
        evidence_graph_payload={},
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    pre_appendix = text.split("Citation Index & Record Appendix")[0]
    assert "1900-01-01" not in pre_appendix


def test_pdf_pt_verified_reported_reconciliation_and_ledger() -> None:
    projection = ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=[])
    citations = [
        Citation(citation_id="cit-pt1", source_document_id="doc-1", page_number=52, snippet="PT daily note 11/19/2024", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="cit-pt2", source_document_id="doc-1", page_number=53, snippet="PT progress note 11/21/2024", bbox=BBox(x=1, y=1, w=1, h=1)),
        Citation(citation_id="cit-rpt", source_document_id="doc-1", page_number=88, snippet="PT discharge summary total visits 141", bbox=BBox(x=1, y=1, w=1, h=1)),
    ]
    pdf_bytes = generate_pdf_from_projection(
        matter_title="PT Reconciliation Case",
        projection=projection,
        gaps=[],
        appendix_entries=[],
        raw_events=[],
        all_citations=citations,
        page_map={52: ("packet.pdf", 52), 53: ("packet.pdf", 53), 88: ("packet.pdf", 88)},
        evidence_graph_payload={
            "extensions": {
                "pt_encounters": [
                    {
                        "encounter_date": "2024-11-19",
                        "provider_name": "Elite Physical Therapy",
                        "facility_name": "Elite Physical Therapy",
                        "encounter_kind": "PT",
                        "source": "primary",
                        "evidence_citation_ids": ["cit-pt1"],
                        "page_number": 52,
                        "dedupe_key": "a",
                    },
                    {
                        "encounter_date": "2024-11-21",
                        "provider_name": "Elite Physical Therapy",
                        "facility_name": "Elite Physical Therapy",
                        "encounter_kind": "PT",
                        "source": "primary",
                        "evidence_citation_ids": ["cit-pt2"],
                        "page_number": 53,
                        "dedupe_key": "b",
                    },
                ],
                "pt_count_reported": [
                    {
                        "reported_count": 141,
                        "report_source_type": "discharge_summary",
                        "evidence_citation_ids": ["cit-rpt"],
                        "page_number": 88,
                    }
                ],
                "pt_reconciliation": {
                    "verified_pt_count": 2,
                    "reported_pt_counts": [141],
                    "reported_pt_count_min": 141,
                    "reported_pt_count_max": 141,
                    "variance_flag": True,
                    "severe_variance_flag": True,
                },
                "litigation_safe_v1": {"status": "REVIEW_RECOMMENDED", "failure_reasons": [], "computed": {"max_gap_days": 0}},
            }
        },
        run_id=None,
    )
    text = _pdf_text(pdf_bytes)
    assert "PT visits (Verified): 2 encounters" in text
    assert "PT visits (Reported in records): 141" in text
    assert "PT Visit Ledger" in text
    assert "Dated PT encounters verified: 1" not in text
