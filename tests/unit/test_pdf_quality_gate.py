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
    assert "PT visits: 117 encounters" in text


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
    assert "Billing extraction status: Incomplete" in text
    assert "Not available from extracted records (incomplete billing extraction)" in text
