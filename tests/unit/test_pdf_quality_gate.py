from datetime import datetime, timezone

import io
from pypdf import PdfReader

from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.export_render.timeline_pdf import generate_pdf_from_projection


def test_pdf_order_and_junk_filter() -> None:
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
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join([p.extract_text() or "" for p in reader.pages])
    assert "Moat Analysis" in full_text
    assert "Executive Summary" in full_text
    assert "Chronological Medical Timeline" in full_text
    assert "Medical Record Appendix" in full_text
    assert full_text.find("Moat Analysis") < full_text.find("Executive Summary")
    assert full_text.find("Executive Summary") < full_text.find("Chronological Medical Timeline")
    assert full_text.find("Chronological Medical Timeline") < full_text.find("Medical Record Appendix")
    assert "Very partner example rate remain better letter vehicle just." not in full_text
