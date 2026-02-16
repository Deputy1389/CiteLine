"""
Unit tests for specials summary aggregation (Phase 5).
"""
import pytest
from decimal import Decimal

from apps.worker.steps.step17_specials_summary import (
    _dedupe_key,
    _to_decimal,
    compute_specials_summary,
)


# ── Deduplication ─────────────────────────────────────────────────────────


class TestDedupeKey:
    def test_same_lines_same_key(self):
        line = {
            "provider_entity_id": "dr smith",
            "service_date": "2024-01-15",
            "code": "99213",
            "amount": "150.00",
            "description": "Office Visit",
        }
        assert _dedupe_key(line) == _dedupe_key(line)

    def test_different_amounts_different_key(self):
        line1 = {"provider_entity_id": "dr smith", "service_date": "2024-01-15",
                 "code": "99213", "amount": "150.00", "description": "Office Visit"}
        line2 = {"provider_entity_id": "dr smith", "service_date": "2024-01-15",
                 "code": "99213", "amount": "200.00", "description": "Office Visit"}
        assert _dedupe_key(line1) != _dedupe_key(line2)

    def test_different_dates_different_key(self):
        line1 = {"provider_entity_id": "dr smith", "service_date": "2024-01-15",
                 "code": "99213", "amount": "150.00", "description": "Office Visit"}
        line2 = {"provider_entity_id": "dr smith", "service_date": "2024-02-15",
                 "code": "99213", "amount": "150.00", "description": "Office Visit"}
        assert _dedupe_key(line1) != _dedupe_key(line2)


# ── Decimal conversion ────────────────────────────────────────────────────


class TestToDecimal:
    def test_string_amount(self):
        assert _to_decimal("150.00") == Decimal("150.00")

    def test_float_amount(self):
        assert _to_decimal(150.0) == Decimal("150.00")

    def test_invalid_returns_zero(self):
        assert _to_decimal("invalid") == Decimal("0.00")

    def test_none_returns_zero(self):
        assert _to_decimal(None) == Decimal("0.00")


# ── Specials summary computation ──────────────────────────────────────────


class TestComputeSpecialsSummary:
    def _sample_billing_payload(self):
        return {
            "line_count": 3,
            "billing_pages_count": 2,
            "lines": [
                {
                    "id": "line1",
                    "provider_entity_id": "dr smith",
                    "service_date": "2024-01-15",
                    "code": "99213",
                    "amount": "150.00",
                    "amount_type": "charge",
                    "description": "Office Visit",
                    "citation_ids": ["c1"],
                    "source_page_numbers": [1],
                    "flags": [],
                },
                {
                    "id": "line2",
                    "provider_entity_id": "dr smith",
                    "service_date": "2024-01-15",
                    "code": "99213",
                    "amount": "50.00",
                    "amount_type": "payment",
                    "description": "Insurance Payment",
                    "citation_ids": ["c2"],
                    "source_page_numbers": [2],
                    "flags": [],
                },
                {
                    "id": "line3",
                    "provider_entity_id": "dr smith",
                    "service_date": "2024-02-15",
                    "code": "99214",
                    "amount": "200.00",
                    "amount_type": "charge",
                    "description": "Office Visit Level 4",
                    "citation_ids": ["c3"],
                    "source_page_numbers": [2],
                    "flags": [],
                },
            ],
        }

    def _sample_providers(self):
        return [{
            "normalized_name": "dr smith",
            "display_name": "Dr. Smith, MD",
            "provider_type": "physician",
            "first_seen_date": "2024-01-15",
            "last_seen_date": "2024-02-15",
            "event_count": 2,
            "citation_count": 3,
            "source_provider_ids": ["p1"],
        }]

    def test_total_charges(self):
        summary = compute_specials_summary(self._sample_billing_payload(), self._sample_providers())
        assert Decimal(summary["totals"]["total_charges"]) == Decimal("350.00")

    def test_total_payments(self):
        summary = compute_specials_summary(self._sample_billing_payload(), self._sample_providers())
        assert Decimal(summary["totals"]["total_payments"]) == Decimal("50.00")

    def test_provider_breakdown(self):
        summary = compute_specials_summary(self._sample_billing_payload(), self._sample_providers())
        assert len(summary["by_provider"]) == 1
        assert summary["by_provider"][0]["provider_display_name"] == "Dr. Smith, MD"
        assert Decimal(summary["by_provider"][0]["charges"]) == Decimal("350.00")

    def test_sum_by_provider_equals_totals(self):
        """Invariant: sum of per-provider charges == total charges."""
        summary = compute_specials_summary(self._sample_billing_payload(), self._sample_providers())
        total = Decimal(summary["totals"]["total_charges"])
        provider_sum = sum(
            Decimal(p["charges"]) for p in summary["by_provider"]
        )
        assert abs(total - provider_sum) <= Decimal("0.01")

    def test_coverage_dates(self):
        summary = compute_specials_summary(self._sample_billing_payload(), self._sample_providers())
        assert summary["coverage"]["earliest_service_date"] == "2024-01-15"
        assert summary["coverage"]["latest_service_date"] == "2024-02-15"

    def test_dedupe_metrics(self):
        summary = compute_specials_summary(self._sample_billing_payload(), self._sample_providers())
        assert summary["dedupe"]["lines_raw"] == 3
        assert summary["dedupe"]["lines_deduped"] <= 3

    def test_empty_billing_data(self):
        summary = compute_specials_summary(
            {"lines": [], "billing_pages_count": 0}, []
        )
        assert "NO_BILLING_DATA" in summary["flags"]
        assert summary["totals"]["total_charges"] == "0.00"
        assert summary["totals"]["total_payments"] is None

    def test_missing_payments_flag(self):
        """If only charges exist, payments should be None and flag present."""
        payload = {
            "line_count": 1,
            "billing_pages_count": 1,
            "lines": [{
                "id": "line1",
                "provider_entity_id": None,
                "service_date": "2024-01-15",
                "code": "99213",
                "amount": "100.00",
                "amount_type": "charge",
                "description": "Visit",
                "citation_ids": ["c1"],
                "source_page_numbers": [1],
                "flags": ["PROVIDER_UNRESOLVED"],
            }],
        }
        summary = compute_specials_summary(payload, [])
        assert "MISSING_EOB_DATA" in summary["flags"]
        assert summary["totals"]["total_payments"] is None

    def test_deterministic(self):
        """Same input produces same output."""
        payload = self._sample_billing_payload()
        providers = self._sample_providers()
        r1 = compute_specials_summary(payload, providers)
        r2 = compute_specials_summary(payload, providers)
        assert r1 == r2

    def test_dedupe_removes_duplicates(self):
        """Identical lines should be deduped."""
        line = {
            "id": "line1",
            "provider_entity_id": "dr smith",
            "service_date": "2024-01-15",
            "code": "99213",
            "amount": "150.00",
            "amount_type": "charge",
            "description": "Office Visit",
            "citation_ids": ["c1"],
            "source_page_numbers": [1],
            "flags": [],
        }
        payload = {"lines": [line, dict(line, id="line2")], "billing_pages_count": 1}
        summary = compute_specials_summary(payload, self._sample_providers())
        assert summary["dedupe"]["lines_raw"] == 2
        assert summary["dedupe"]["lines_deduped"] == 1
        # Only one line after dedupe, so charges = 150 not 300
        assert Decimal(summary["totals"]["total_charges"]) == Decimal("150.00")
