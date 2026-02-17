"""
Unit tests for Step 12 — Export rendering (DOCX focus).
"""
from __future__ import annotations

from datetime import date

import pytest

from packages.shared.models import (
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Gap,
    Provider,
    ProviderType,
    DateKind,
    DateSource,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

def _make_event(
    event_id: str = "evt-1",
    event_type: EventType = EventType.OFFICE_VISIT,
    with_date: bool = True,
    flags: list[str] | None = None,
    confidence: int = 85,
) -> Event:
    dt = None
    if with_date:
        dt = EventDate(
            kind=DateKind.SINGLE,
            value=date(2024, 3, 15),
            source=DateSource.TIER1,
        )
    return Event(
        event_id=event_id,
        provider_id="prov-1",
        event_type=event_type,
        date=dt,
        facts=[
            Fact(text="Patient presented with lower back pain", kind=FactKind.CHIEF_COMPLAINT, verbatim=True, citation_id="cit-1"),
            Fact(text="Prescribed ibuprofen 600mg", kind=FactKind.PLAN, verbatim=True, citation_id="cit-2"),
        ],
        confidence=confidence,
        flags=flags or [],
        citation_ids=["cit-1", "cit-2"],
        source_page_numbers=[1, 2],
    )


def _make_provider() -> Provider:
    return Provider(
        provider_id="prov-1",
        detected_name_raw="Dr. Smith",
        normalized_name="Dr. Smith, MD",
        provider_type=ProviderType.SPECIALIST,
        confidence=90,
    )


def _make_gap() -> Gap:
    return Gap(
        gap_id="gap-1",
        start_date=date(2024, 3, 15),
        end_date=date(2024, 5, 1),
        duration_days=47,
        threshold_days=45,
        confidence=80,
    )


# ── DOCX Tests ────────────────────────────────────────────────────────────


class TestGenerateDocx:
    def test_produces_valid_docx(self):
        from apps.worker.steps.step12_export import generate_docx

        events = [_make_event()]
        providers = [_make_provider()]
        gaps = [_make_gap()]

        docx_bytes = generate_docx("run-123", "Smith v Jones", events, gaps, providers)
        # DOCX files are ZIP archives starting with PK
        assert len(docx_bytes) > 100
        assert docx_bytes[:2] == b"PK"

    def test_empty_events(self):
        from apps.worker.steps.step12_export import generate_docx

        docx_bytes = generate_docx("run-456", "Empty Case", [], [], [])
        assert len(docx_bytes) > 100
        assert docx_bytes[:2] == b"PK"

    def test_partitions_flagged_events(self):
        from apps.worker.steps.step12_export import generate_docx
        from docx import Document as DocxDocument

        dated = _make_event(event_id="dated-1")
        flagged = _make_event(
            event_id="flagged-1",
            flags=["MISSING_SOURCE", "NEEDS_REVIEW"],
        )
        undated = _make_event(event_id="undated-1", with_date=False)

        docx_bytes = generate_docx(
            "run-789", "Test Case",
            [dated, flagged, undated], [], [_make_provider()],
        )

        # Parse the DOCX and verify sections exist
        import io
        doc = DocxDocument(io.BytesIO(docx_bytes))
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert "Chronology" in headings
        assert "Undated / Needs Review" in headings

    def test_includes_summary_stats(self):
        from apps.worker.steps.step12_export import generate_docx
        from docx import Document as DocxDocument

        events = [_make_event(), _make_event(event_id="evt-2")]
        docx_bytes = generate_docx("run-abc", "Stats Case", events, [], [_make_provider()])

        import io
        doc = DocxDocument(io.BytesIO(docx_bytes))
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert "Summary" in headings

    def test_with_page_map(self):
        from apps.worker.steps.step12_export import generate_docx

        events = [_make_event()]
        page_map = {1: ("medical_records.pdf", 1), 2: ("medical_records.pdf", 2)}

        docx_bytes = generate_docx(
            "run-map", "Provenance Case",
            events, [], [_make_provider()], page_map=page_map,
        )
        assert len(docx_bytes) > 100

    def test_treatment_gaps_section(self):
        from apps.worker.steps.step12_export import generate_docx
        from docx import Document as DocxDocument

        gaps = [_make_gap()]
        docx_bytes = generate_docx("run-gap", "Gap Case", [_make_event()], gaps, [_make_provider()])

        import io
        doc = DocxDocument(io.BytesIO(docx_bytes))
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert "Appendix: Treatment Gaps" in headings

    def test_narrative_mode_still_includes_chronology(self):
        from apps.worker.steps.step12_export import generate_docx
        from docx import Document as DocxDocument

        events = [
            _make_event(event_id="evt-a"),
            _make_event(event_id="evt-b"),
            _make_event(event_id="evt-c"),
        ]
        docx_bytes = generate_docx(
            "run-narrative",
            "Narrative Case",
            events,
            [],
            [_make_provider()],
            narrative_synthesis="Narrative summary",
        )

        import io
        doc = DocxDocument(io.BytesIO(docx_bytes))
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert "Chronology" in headings


# ── PDF sanity ────────────────────────────────────────────────────────────


class TestGeneratePdf:
    def test_produces_valid_pdf(self):
        from apps.worker.steps.step12_export import generate_pdf

        events = [_make_event()]
        providers = [_make_provider()]

        pdf_bytes = generate_pdf("run-pdf", "PDF Case", events, [], providers)
        assert len(pdf_bytes) > 100
        assert pdf_bytes[:5] == b"%PDF-"


# ── CSV sanity ────────────────────────────────────────────────────────────


class TestGenerateCsv:
    def test_produces_csv_with_header(self):
        from apps.worker.steps.step12_export import generate_csv

        events = [_make_event()]
        providers = [_make_provider()]

        csv_bytes = generate_csv(events, providers)
        csv_text = csv_bytes.decode("utf-8")

        assert "event_id" in csv_text
        assert "evt-1" in csv_text

    def test_includes_events_with_missing_provider_id(self):
        from apps.worker.steps.step12_export import generate_csv

        event = _make_event()
        event.provider_id = None
        csv_bytes = generate_csv([event], [_make_provider()])
        csv_text = csv_bytes.decode("utf-8")

        assert "evt-1" in csv_text
        assert "Unknown" in csv_text
