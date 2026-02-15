"""
Unit tests for page type classifier (Step 3).
"""
import pytest
from packages.shared.models import Page, PageType
from apps.worker.steps.step03_classify import classify_page, classify_pages


def _make_page(text: str, page_number: int = 1) -> Page:
    return Page(
        page_id="test-page",
        source_document_id="test-doc",
        page_number=page_number,
        text=text,
        text_source="embedded_pdf_text",
    )


class TestClassifyPage:
    def test_clinical_note(self):
        page = _make_page("Chief Complaint: Back pain\nAssessment: Lumbar strain\nPlan: Physical therapy")
        ptype, conf = classify_page(page)
        assert ptype == PageType.CLINICAL_NOTE
        assert conf >= 60

    def test_imaging_report(self):
        page = _make_page("MRI Lumbar Spine\nTechnique: Standard protocol\nImpression: Disc herniation\nFindings: L4-L5")
        ptype, conf = classify_page(page)
        assert ptype == PageType.IMAGING_REPORT
        assert conf >= 60

    def test_operative_report(self):
        page = _make_page("Operative Report\nProcedure: Lumbar discectomy\nAnesthesia: General\nPre-op diagnosis: Herniated disc")
        ptype, conf = classify_page(page)
        assert ptype == PageType.OPERATIVE_REPORT
        assert conf >= 60

    def test_billing(self):
        page = _make_page("Statement of Charges\nTotal Due: $500.00\nCPT 99214\nBalance: $500.00")
        ptype, conf = classify_page(page)
        assert ptype == PageType.BILLING
        assert conf >= 60

    def test_pt_note(self):
        page = _make_page("Physical Therapy Daily Note\nExercise: Core stabilization\nPlan of Care: 3x/week")
        ptype, conf = classify_page(page)
        assert ptype == PageType.PT_NOTE
        assert conf >= 60

    def test_administrative(self):
        page = _make_page("Fax Cover Sheet\nAuthorization Request\nRelease of Information")
        ptype, conf = classify_page(page)
        assert ptype == PageType.ADMINISTRATIVE
        assert conf >= 50

    def test_other_fallback(self):
        page = _make_page("This is some random text with no medical keywords at all.")
        ptype, conf = classify_page(page)
        assert ptype == PageType.OTHER
        assert conf <= 50

    def test_priority_operative_over_clinical(self):
        """Operative should win when both operative and clinical keywords present."""
        page = _make_page("Operative Report\nProcedure performed\nChief Complaint: pain\nAssessment: stable")
        ptype, _ = classify_page(page)
        assert ptype == PageType.OPERATIVE_REPORT

    def test_classify_pages_sets_page_type(self):
        pages = [
            _make_page("Chief Complaint: headache\nAssessment: migraine", 1),
            _make_page("Total Due: $100\nCharges: Office visit", 2),
        ]
        updated, warnings = classify_pages(pages)
        assert updated[0].page_type == PageType.CLINICAL_NOTE
        assert updated[1].page_type == PageType.BILLING
