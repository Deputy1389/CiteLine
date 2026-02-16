"""
Unit tests for provider normalization (Step 5).
"""
import pytest
from apps.worker.steps.step05_provider import _normalize_name, _simple_fuzzy_match, _is_valid_candidate


class TestProviderNormalization:
    def test_lowercase(self):
        assert _normalize_name("SOUTHWEST MEDICAL") == "southwest medical"

    def test_strip_llc(self):
        result = _normalize_name("Southwest Medical LLC")
        assert "llc" not in result

    def test_strip_inc(self):
        result = _normalize_name("Acme Health Inc")
        assert "inc" not in result

    def test_strip_medical_group(self):
        result = _normalize_name("Valley Orthopedic Medical Group")
        assert "medical group" not in result

    def test_standardize_saint(self):
        result = _normalize_name("Saint Joseph Hospital")
        assert "st" in result
        assert "saint" not in result

    def test_standardize_center(self):
        result = _normalize_name("Southwest Medical Center")
        assert "ctr" in result
        assert "center" not in result

    def test_strip_punctuation(self):
        result = _normalize_name("Dr. Smith's Clinic, P.A.")
        assert "." not in result
        assert "," not in result
        assert "'" not in result

    def test_collapse_whitespace(self):
        result = _normalize_name("Southwest   Regional    Medical")
        assert "  " not in result

    def test_empty_string(self):
        result = _normalize_name("")
        assert result == ""


class TestFuzzyMatch:
    def test_exact_match(self):
        score = _simple_fuzzy_match("southwest medical", "southwest medical")
        assert score == 1.0

    def test_partial_match(self):
        score = _simple_fuzzy_match("southwest medical center", "southwest medical")
        assert score > 0.5

    def test_no_match(self):
        score = _simple_fuzzy_match("southwest medical", "pinnacle therapy")
        assert score < 0.3

    def test_empty_strings(self):
        assert _simple_fuzzy_match("", "") == 0.0
        assert _simple_fuzzy_match("test", "") == 0.0


class TestProviderFiltering:
    """Tests for the _is_valid_candidate filter (P2)."""

    def test_valid_provider_name(self):
        assert _is_valid_candidate("Southwest Medical Center") is True

    def test_valid_short_name(self):
        assert _is_valid_candidate("Dr. Smith") is True

    def test_reject_too_short(self):
        assert _is_valid_candidate("AB") is False

    def test_reject_too_long(self):
        assert _is_valid_candidate("A" * 121) is False

    def test_reject_ends_with_period(self):
        assert _is_valid_candidate("The patient was seen for follow-up visit today.") is False

    def test_reject_too_many_words(self):
        long_sentence = "The patient was referred to the orthopedic clinic for further evaluation of the left knee injury sustained"
        assert _is_valid_candidate(long_sentence) is False

    def test_reject_sentence_like_lowercase(self):
        # High lowercase ratio + >3 words → sentence-like
        assert _is_valid_candidate("the patient was seen for back pain today") is False

    def test_accept_uppercase_facility(self):
        # Title-case or uppercase names should pass even if many words
        assert _is_valid_candidate("SOUTHWEST REGIONAL MEDICAL CENTER") is True

    def test_accept_mixed_case_provider(self):
        assert _is_valid_candidate("Valley Orthopedic Medical") is True

    def test_accept_labeled_provider(self):
        assert _is_valid_candidate("John Smith MD") is True

