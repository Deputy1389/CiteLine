from apps.worker.steps import step02_text_acquire as ocr


class _FakePage:
    def __init__(self, images: int = 0, font_spans: int = 0):
        self._images = images
        self._font_spans = font_spans

    def get_images(self):
        return [object()] * self._images

    def get_text(self, _mode: str):
        spans = []
        for _ in range(self._font_spans):
            spans.append({"font": "Helvetica"})
        if not spans:
            return {"blocks": []}
        return {"blocks": [{"lines": [{"spans": spans}]}]}


def test_quality_warning_flags_garbage() -> None:
    assert ocr._quality_warning("") is True
    assert ocr._quality_warning("     ") is True
    assert ocr._quality_warning("### $$$ ***") is True
    assert ocr._quality_warning("Patient reports ongoing back pain after MVC with treatment and follow-up.") is False


def test_page_needs_ocr_skips_meaningful_text() -> None:
    page = _FakePage(images=0, font_spans=3)
    assert ocr._page_needs_ocr("This is meaningful text with more than fifty characters.", page) is False


def test_page_needs_ocr_skips_blank_separator() -> None:
    page = _FakePage(images=0, font_spans=0)
    assert ocr._page_needs_ocr("", page) is False


def test_page_needs_ocr_flags_low_density_text() -> None:
    page = _FakePage(images=1, font_spans=0)
    assert ocr._page_needs_ocr("Header only", page) is True
