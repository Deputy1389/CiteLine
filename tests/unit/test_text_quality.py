from apps.worker.quality.text_quality import clean_text, is_garbage, quality_score, explain_flags


def test_clean_text_removes_fax_headers() -> None:
    raw = "FROM: 555-123-4567\nTO: 555-999-0000\nPatient reports back pain after MVC."
    cleaned = clean_text(raw)
    assert "FROM" not in cleaned
    assert "TO" not in cleaned
    assert "Patient reports back pain" in cleaned


def test_garbage_detection_flags_nonsense() -> None:
    junk = "Very partner example rate remain better letter vehicle just."
    assert is_garbage(junk) is False
    assert quality_score(junk) < 0.3
    assert "low_medical_density" in explain_flags(junk)


def test_real_sentence_not_garbage() -> None:
    good = "Patient reports persistent lumbar pain with radiculopathy; MRI shows L4-5 disc protrusion."
    assert is_garbage(good) is False
    assert quality_score(good) > 0.3
