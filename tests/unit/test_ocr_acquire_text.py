import types
import sys
from contextlib import contextmanager

import apps.worker.steps.step02_text_acquire as ocr
from packages.shared.models.domain import Page


class _DummyDoc:
    def __getitem__(self, _idx):
        return object()

    def close(self):
        return None


@contextmanager
def _dummy_session():
    class _Session:
        def query(self, *args, **kwargs):
            class _Q:
                def filter(self, *a, **k):
                    return self

                def filter_by(self, *a, **k):
                    return self

                def all(self):
                    return []

                def one_or_none(self):
                    return None

            return _Q()

    yield _Session()


def _page(text: str) -> Page:
    return Page(
        page_id="p1",
        source_document_id="doc1",
        page_number=1,
        text=text,
        text_source="embedded_pdf_text",
    )


def test_acquire_text_ocr_disabled(monkeypatch):
    monkeypatch.setattr(ocr, "_OCR_DISABLED", True)
    pages, count, warnings = ocr.acquire_text([_page("")], "dummy.pdf", run_id=None)
    assert count == 0
    assert any(w.code == "OCR_DISABLED" for w in warnings)


def test_acquire_text_ocr_unavailable(monkeypatch):
    monkeypatch.setattr(ocr, "_OCR_DISABLED", False)
    monkeypatch.setattr(ocr, "_check_tesseract", lambda: False)
    pages, count, warnings = ocr.acquire_text([_page("")], "dummy.pdf", run_id=None)
    assert count == 0
    assert any(w.code == "OCR_UNAVAILABLE" for w in warnings)


def test_acquire_text_runs_ocr(monkeypatch):
    monkeypatch.setattr(ocr, "_OCR_DISABLED", False)
    monkeypatch.setattr(ocr, "_check_tesseract", lambda: True)
    monkeypatch.setattr(ocr, "_page_needs_ocr", lambda *_: True)
    monkeypatch.setattr(ocr, "_ocr_page", lambda *a, **k: "OCR text")
    monkeypatch.setattr(ocr, "fitz", types.SimpleNamespace(open=lambda _: _DummyDoc()))
    monkeypatch.setattr(ocr, "get_session", _dummy_session)

    pages, count, warnings = ocr.acquire_text([_page("")], "dummy.pdf", run_id=None)
    assert pages[0].text == "OCR text"
    assert count == 1
    assert any(w.code == "OCR_QUALITY_LOW" for w in warnings)


def test_acquire_text_budget_exceeded(monkeypatch):
    monkeypatch.setattr(ocr, "_OCR_DISABLED", False)
    monkeypatch.setattr(ocr, "_check_tesseract", lambda: True)
    monkeypatch.setattr(ocr, "_page_needs_ocr", lambda *_: True)
    monkeypatch.setattr(ocr, "_ocr_page", lambda *a, **k: "OCR text")
    monkeypatch.setattr(ocr, "fitz", types.SimpleNamespace(open=lambda _: _DummyDoc()))
    monkeypatch.setattr(ocr, "get_session", _dummy_session)
    monkeypatch.setattr(ocr, "_OCR_TOTAL_TIMEOUT_SECONDS", 0)

    pages, count, warnings = ocr.acquire_text([_page("")], "dummy.pdf", run_id=None)
    assert any(w.code == "OCR_BUDGET_EXCEEDED" for w in warnings)


def test_ocr_page_retries_at_lower_dpi_after_timeout(monkeypatch):
    class _FakePix:
        def tobytes(self, _fmt):
            from PIL import Image
            import io

            img = Image.new("L", (200, 200), "white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

    class _FakePage:
        def __init__(self):
            self.dpis = []

        def get_pixmap(self, *, dpi, colorspace, alpha):
            self.dpis.append(dpi)
            return _FakePix()

    class _FakeDoc:
        def __init__(self, page):
            self.page = page

        def __getitem__(self, _idx):
            return self.page

        def close(self):
            return None

    calls = {"count": 0}

    class _FakeTesseract:
        @staticmethod
        def image_to_string(_img, lang, config, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("Tesseract process timeout")
            return "Recovered OCR"

    page = _FakePage()
    monkeypatch.setitem(sys.modules, "pytesseract", _FakeTesseract)
    monkeypatch.setattr(ocr, "_OCR_RETRY_DPI", 120)
    text = ocr._ocr_page("dummy.pdf", 0, dpi=200, config="--psm 6", doc=_FakeDoc(page))
    assert text == "Recovered OCR"
    assert page.dpis == [200, 120]
