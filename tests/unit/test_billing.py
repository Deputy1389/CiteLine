"""
Unit tests for billing extraction primitives (Phase 4).
"""
import pytest
from datetime import date

from apps.worker.lib.billing_extract import (
    classify_amount_type,
    extract_billing_date,
    extract_codes,
    is_billing_text,
    parse_amounts,
)


# ── Amount parsing ────────────────────────────────────────────────────────


class TestParseAmounts:
    def test_simple_dollar(self):
        amounts = parse_amounts("Total: $1,234.56")
        assert len(amounts) >= 1
        assert any(abs(a[0] - 1234.56) < 0.01 for a in amounts)

    def test_negative_paren(self):
        amounts = parse_amounts("Adjustment: ($50.00)")
        assert any(a[0] < 0 for a in amounts)

    def test_negative_dash(self):
        amounts = parse_amounts("Payment: -$100.00")
        assert any(a[0] < 0 for a in amounts)

    def test_multiple_amounts(self):
        amounts = parse_amounts("Charge $200.00 Payment $50.00 Balance $150.00")
        assert len(amounts) >= 3

    def test_no_amounts(self):
        amounts = parse_amounts("No dollar amounts here")
        assert len(amounts) == 0

    def test_zero_filtered(self):
        amounts = parse_amounts("$0.00")
        assert len(amounts) == 0


# ── Amount type classification ────────────────────────────────────────────


class TestClassifyAmountType:
    def test_charge(self):
        assert classify_amount_type("Total Charges: $500") == "charge"

    def test_payment(self):
        assert classify_amount_type("Insurance Payment: $300") == "payment"

    def test_adjustment(self):
        assert classify_amount_type("Contractual Adjustment: $100") == "adjustment"

    def test_copay(self):
        assert classify_amount_type("Copay collected: $25") == "copay"

    def test_deductible(self):
        assert classify_amount_type("Deductible remaining: $150") == "deductible"

    def test_balance(self):
        assert classify_amount_type("Amount Due: $75") == "balance"

    def test_writeoff(self):
        assert classify_amount_type("Write-off: $20") == "writeoff"

    def test_unknown(self):
        assert classify_amount_type("Something: $50") == "unknown"


# ── Code extraction ───────────────────────────────────────────────────────


class TestExtractCodes:
    def test_cpt_code(self):
        codes = extract_codes("99213 Office Visit")
        assert "99213" in codes

    def test_hcpcs_code(self):
        codes = extract_codes("J1234 injection")
        assert "J1234" in codes

    def test_icd_code(self):
        codes = extract_codes("Diagnosis: M54.5")
        assert "M54.5" in codes

    def test_year_filtered(self):
        codes = extract_codes("Date: 2024 CPT 99213")
        assert "2024" not in [c for c in codes if c.isdigit() and len(c) == 5]
        assert "99213" in codes

    def test_no_codes(self):
        codes = extract_codes("No billing codes here.")
        assert len(codes) == 0

    def test_deduplication(self):
        codes = extract_codes("99213 99213 99213")
        assert codes.count("99213") == 1


# ── Date extraction ───────────────────────────────────────────────────────


class TestExtractBillingDate:
    def test_mm_dd_yyyy(self):
        d = extract_billing_date("Service Date: 01/15/2024")
        assert d == date(2024, 1, 15)

    def test_mm_dd_yy(self):
        d = extract_billing_date("Date: 03/20/24")
        assert d == date(2024, 3, 20)

    def test_dash_separator(self):
        d = extract_billing_date("Date: 12-25-2023")
        assert d == date(2023, 12, 25)

    def test_no_date(self):
        d = extract_billing_date("No date here")
        assert d is None

    def test_invalid_date(self):
        d = extract_billing_date("Date: 13/45/2024")
        assert d is None


# ── Billing text detection ────────────────────────────────────────────────


class TestIsBillingText:
    def test_billing_text(self):
        text = "Total Charges: $500 CPT 99213 Payment received"
        assert is_billing_text(text) is True

    def test_clinical_text(self):
        text = "Chief complaint: low back pain. Exam: normal range of motion."
        assert is_billing_text(text) is False

    def test_minimal_billing(self):
        text = "Statement date: EOB attached"
        assert is_billing_text(text) is True
