"""
Unit tests for provider normalization (Step 5).
"""
import pytest
from apps.worker.steps.step05_provider import _normalize_name, _simple_fuzzy_match


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
