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


# ── Provider header extraction ────────────────────────────────────────────


class TestExtractProviderFromHeader:
    def test_billed_by_prefix(self):
        from apps.worker.lib.billing_extract import extract_provider_from_header
        text = "Billed by: ABC Medical Group\nAccount: 12345\n$500.00"
        assert extract_provider_from_header(text) == "ABC Medical Group"

    def test_facility_pattern(self):
        from apps.worker.lib.billing_extract import extract_provider_from_header
        text = "Springfield General Hospital\n123 Main St\nDate: 01/15/2024\n$200.00"
        result = extract_provider_from_header(text)
        assert result is not None
        assert "Hospital" in result

    def test_doctor_with_credentials(self):
        from apps.worker.lib.billing_extract import extract_provider_from_header
        text = "Dr. John Smith, M.D.\nSpecialty: Orthopedics\n$300.00"
        result = extract_provider_from_header(text)
        assert result is not None
        assert "Smith" in result

    def test_no_provider_found(self):
        from apps.worker.lib.billing_extract import extract_provider_from_header
        text = "$100.00\n$200.00\n$300.00"
        assert extract_provider_from_header(text) is None

    def test_max_lines_limit(self):
        from apps.worker.lib.billing_extract import extract_provider_from_header
        # Provider after max_lines should not be found
        lines = ["line " + str(i) for i in range(15)]
        lines.append("Billed by: Late Provider")
        text = "\n".join(lines)
        assert extract_provider_from_header(text, max_lines=8) is None


# ── Table parsing ─────────────────────────────────────────────────────────


class TestParseBillingTable:
    def test_simple_table(self):
        from apps.worker.lib.billing_extract import parse_billing_table
        text = (
            "Description         Charges\n"
            "Office Visit 99213  $150.00\n"
            "Lab Work            $75.00\n"
            "X-Ray               $200.00\n"
        )
        items = parse_billing_table(text)
        assert len(items) >= 1
        # Check amounts were extracted
        all_amounts = [a for item in items for a in item["amounts"]]
        assert any(abs(a - 150.0) < 0.01 for a in all_amounts)

    def test_no_table_structure(self):
        from apps.worker.lib.billing_extract import parse_billing_table
        text = "Some plain text without any dollar amounts."
        items = parse_billing_table(text)
        assert items == []

    def test_short_text_returns_empty(self):
        from apps.worker.lib.billing_extract import parse_billing_table
        text = "$100.00"
        items = parse_billing_table(text)
        assert items == []

    def test_multi_line_entry(self):
        from apps.worker.lib.billing_extract import parse_billing_table
        text = (
            "Office Visit\n"
            "Level 4 Follow-up\n"
            "99214                $250.00\n"
            "\n"
            "Lab CBC              $45.00\n"
        )
        items = parse_billing_table(text)
        # Should have at least one item with code 99214
        codes_found = [c for item in items for c in item["codes"]]
        assert "99214" in codes_found


# ── Extended amount type classification ───────────────────────────────────


class TestExtendedAmountTypes:
    def test_insurance_paid(self):
        assert classify_amount_type("Insurance Paid: $300") == "payment"

    def test_net_due(self):
        assert classify_amount_type("Net Due: $75") == "balance"

    def test_net_balance(self):
        assert classify_amount_type("Net Balance: $120") == "balance"

    def test_patient_balance(self):
        assert classify_amount_type("Patient Balance: $50") == "balance"
