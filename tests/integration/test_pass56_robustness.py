from __future__ import annotations

from packages.shared.models import Page
from apps.worker.pipeline import _apply_render_blockers_to_gate_results
from apps.worker.steps.step06_dates import extract_dates
from apps.worker.steps.events.clinical import extract_clinical_events
from packages.shared.models import RunConfig, PageType


def _page(text: str, page_number: int = 1, page_type: PageType = PageType.CLINICAL_NOTE) -> Page:
    return Page(
        page_id=f"p-{page_number}",
        source_document_id="doc-1",
        page_number=page_number,
        text=text,
        text_source="embedded_pdf_text",
        page_type=page_type,
    )


def test_future_year_dates_are_extracted_not_dropped() -> None:
    page = _page("Date of Service: 03/14/2180\nChief Complaint: back pain")
    dates = extract_dates(page)
    assert dates
    assert str(dates[0][0].value) == "2180-03-14"


def test_structured_medical_rows_survive_clinical_extraction() -> None:
    page = _page("Vitals\nBP 132/88\nHR 72\nNa 138\nWBC 12.4")
    events, citations, warnings, skipped = extract_clinical_events(
        [page],
        dates={},
        providers=[],
        config=RunConfig(),
    )
    assert events
    fact_texts = [fact.text for event in events for fact in event.facts]
    assert any("BP 132/88" in text for text in fact_texts)
    assert any("Na 138" in text for text in fact_texts)


def test_render_blockers_force_blocked_export_status() -> None:
    gate_results = {"export_status": "VERIFIED", "hard_failures": []}
    extensions = {
        "render_blockers": [
            {
                "code": "ED_EXISTS_BUT_NOT_RENDERED",
                "severity": "hard",
                "message": "ED evidence exists but was not rendered.",
            }
        ]
    }
    out = _apply_render_blockers_to_gate_results(gate_results, extensions)
    assert out["export_status"] == "BLOCKED"
    assert out["render_blocker_count"] == 1
    assert any(f.get("code") == "ED_EXISTS_BUT_NOT_RENDERED" for f in out["hard_failures"])
