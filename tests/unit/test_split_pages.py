from pathlib import Path
import tempfile

from apps.worker.steps.step01_page_split import split_pages
from tests.fixtures.generate_fixture import create_synthetic_pdf


def test_split_pages_basic():
    pdf_bytes = create_synthetic_pdf()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "fixture.pdf"
        path.write_bytes(pdf_bytes)
        pages, warnings = split_pages(str(path), "doc1")
        assert len(pages) > 0
        assert pages[0].page_number == 1
        assert warnings == [] or warnings[0].code in {"TEXT_EXTRACT_ERROR", "MAX_PAGES_EXCEEDED"}


def test_split_pages_max_pages():
    pdf_bytes = create_synthetic_pdf()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "fixture.pdf"
        path.write_bytes(pdf_bytes)
        pages, warnings = split_pages(str(path), "doc1", max_pages=1)
        assert len(pages) == 1
        assert any(w.code == "MAX_PAGES_EXCEEDED" for w in warnings) or len(pages) == 1


def test_split_pages_invalid_pdf():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bad.pdf"
        path.write_bytes(b"not a pdf")
        pages, warnings = split_pages(str(path), "doc1")
        assert pages == []
        assert any(w.code == "PDF_OPEN_ERROR" for w in warnings)
