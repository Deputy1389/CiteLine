"""
Billing line extraction utilities (Phase 4).

Deterministic extraction of atomic billing lines from billing pages:
- Dollar amounts with sign/type classification
- CPT/HCPCS/ICD code detection
- Date parsing from billing contexts
- Provider linking via page header cues
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional


# ── Amount parsing ────────────────────────────────────────────────────────

_AMOUNT_PATTERN = re.compile(
    r"""
    (?:^|(?<=\s))                          # start or whitespace
    (?P<neg>-|\()?                         # optional negative indicator
    \$?\s*                                 # optional dollar sign
    (?P<amount>[\d,]+\.?\d*)               # digits with optional decimal
    (?:\))?                                # optional closing paren
    """,
    re.VERBOSE,
)


def parse_amounts(text: str) -> list[tuple[float, int, int]]:
    """
    Extract all dollar amounts from text.
    Returns list of (amount, start_pos, end_pos).
    Negative amounts indicated by '-' or '(...)' are returned as negative.
    """
    results = []
    for m in _AMOUNT_PATTERN.finditer(text):
        try:
            raw = m.group("amount").replace(",", "")
            if not raw or raw == ".":
                continue
            val = float(raw)
            if val == 0:
                continue
            if m.group("neg"):
                val = -val
            results.append((val, m.start(), m.end()))
        except (ValueError, AttributeError):
            continue
    return results


# ── Amount type classification ────────────────────────────────────────────

_AMOUNT_TYPE_RULES: list[tuple[str, str]] = [
    # (keyword_pattern, amount_type)
    (r"(?:co[\s-]*pay|copay)", "copay"),
    (r"(?:co[\s-]*insurance|coinsurance)", "coinsurance"),
    (r"deductible", "deductible"),
    (r"write[\s-]*off", "writeoff"),
    (r"adjustment|adjust|contractual", "adjustment"),
    (r"(?:payment|paid|receipt|remit|insurance\s*paid)", "payment"),
    (r"(?:balance\s*(?:due|forward)?|amount\s*(?:due|owed)|net\s*(?:due|balance)|patient\s*balance)", "balance"),
    (r"(?:charge|billed|total\s*charge|service\s*charge|fee)", "charge"),
    (r"(?:patient\s*responsibility|patient\s*portion)", "balance"),
]

_COMPILED_TYPE_RULES = [
    (re.compile(pat, re.IGNORECASE), atype) for pat, atype in _AMOUNT_TYPE_RULES
]


def classify_amount_type(context: str) -> str:
    """
    Classify amount type from surrounding text context.
    Returns one of: charge, payment, adjustment, balance, copay, deductible,
                    coinsurance, writeoff, unknown.
    """
    for pattern, atype in _COMPILED_TYPE_RULES:
        if pattern.search(context):
            return atype
    return "unknown"


# ── Code extraction ───────────────────────────────────────────────────────

_CPT_PATTERN = re.compile(r"\b(\d{5})\b")  # 5-digit CPT codes
_HCPCS_PATTERN = re.compile(r"\b([A-V]\d{4})\b")  # HCPCS Level II
_ICD_PATTERN = re.compile(r"\b([A-Z]\d{2}(?:\.\d{1,4})?)\b")  # ICD-10
_REVENUE_CODE = re.compile(r"\b(0\d{3})\b")  # Revenue codes


def extract_codes(text: str) -> list[str]:
    """Extract medical billing codes from text."""
    codes = []
    for m in _HCPCS_PATTERN.finditer(text):
        codes.append(m.group(1))
    for m in _CPT_PATTERN.finditer(text):
        val = m.group(1)
        # Filter out years and common non-code numbers
        if not (val.startswith("19") or val.startswith("20")):
            codes.append(val)
    for m in _ICD_PATTERN.finditer(text):
        codes.append(m.group(1))
    return list(dict.fromkeys(codes))  # Dedupe preserving order


# ── Date extraction from billing context ──────────────────────────────────

_DATE_PATTERNS = [
    re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})"),  # MM/DD/YYYY
    re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})"),   # MM/DD/YY
]


def extract_billing_date(text: str) -> Optional[date]:
    """Extract a date from billing line context."""
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if year < 100:
                    year += 2000
                if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
                    return date(year, month, day)
            except (ValueError, OverflowError):
                continue
    return None


# ── Billing keyword density ──────────────────────────────────────────────

_BILLING_KEYWORDS = [
    "total charges", "amount due", "cpt", "hcpcs", "revenue code",
    "eob", "patient responsibility", "insurance", "copay", "deductible",
    "billed", "payment", "adjustment", "balance", "statement",
    "billing", "ledger",
]


def is_billing_text(text: str) -> bool:
    """Check if text has sufficient billing keyword density."""
    lower = text.lower()
    hits = sum(1 for kw in _BILLING_KEYWORDS if kw in lower)
    return hits >= 2


# ── Provider extraction from billing page header ─────────────────────────

_PROVIDER_HEADER_PATTERNS = [
    re.compile(r"(?:from|billed?\s*by|provider|facility|rendered\s*by)[:\s]+(.+)", re.IGNORECASE),
    re.compile(r"^([A-Z][A-Za-z\s&,.'-]{5,60}(?:Medical|Health|Hospital|Clinic|Center|Associates|Group|Surgery|Ortho|Physical\s*Therapy))", re.MULTILINE),
    re.compile(r"^((?:Dr\.?\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3},?\s*(?:M\.?D\.?|D\.?O\.?|D\.?C\.?|P\.?T\.?|D\.?P\.?T\.?))", re.MULTILINE),
]


def extract_provider_from_header(text: str, max_lines: int = 8) -> Optional[str]:
    """
    Scan the first N lines of a billing page for provider identifiers.
    Returns the extracted provider name or None.
    """
    header = "\n".join(text.split("\n")[:max_lines])
    for pat in _PROVIDER_HEADER_PATTERNS:
        m = pat.search(header)
        if m:
            name = m.group(1).strip().rstrip(",.:;")
            if len(name) >= 3 and len(name) <= 120:
                return name
    return None


# ── Tabular billing layout detection & parsing ───────────────────────────

def _detect_column_positions(lines: list[str]) -> list[int]:
    """
    Detect dollar-sign column positions across multiple lines.
    Returns sorted list of character positions where $ signs cluster.
    """
    dollar_positions: dict[int, int] = {}
    for line in lines:
        for i, ch in enumerate(line):
            if ch == "$":
                # Bucket positions within ±2 chars
                bucket = (i // 3) * 3
                dollar_positions[bucket] = dollar_positions.get(bucket, 0) + 1

    # A column exists if $ appears in that bucket in ≥2 lines
    cols = sorted(pos for pos, count in dollar_positions.items() if count >= 2)
    return cols


def parse_billing_table(text: str) -> list[dict]:
    """
    Parse tabular billing layouts into structured billing items.

    Detects column-aligned amounts and groups multi-line entries
    into single billing items. Falls back gracefully to empty list
    if no tabular structure is detected.

    Returns list of dicts with keys:
        description, amounts (list[float]), codes (list[str]),
        service_date (date|None), amount_type (str)
    """
    lines = text.split("\n")
    if len(lines) < 3:
        return []

    # Check for tabular structure
    col_positions = _detect_column_positions(lines)
    if len(col_positions) < 1:
        return []

    items: list[dict] = []
    current_desc_lines: list[str] = []
    current_amounts: list[float] = []
    current_codes: list[str] = []
    current_date: Optional[date] = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # Blank line: flush current item
            if current_amounts:
                desc = " ".join(current_desc_lines).strip()
                if len(desc) > 200:
                    desc = desc[:200]
                items.append({
                    "description": desc,
                    "amounts": current_amounts,
                    "codes": current_codes,
                    "service_date": current_date,
                    "amount_type": classify_amount_type(desc),
                })
            current_desc_lines = []
            current_amounts = []
            current_codes = []
            current_date = None
            continue

        line_amounts = parse_amounts(stripped)
        line_codes = extract_codes(stripped)
        line_date = extract_billing_date(stripped)

        if line_amounts:
            # This line has amounts — it's either a new item or continuation
            if current_amounts and not current_desc_lines:
                # Continuation of amounts without description — treat as new item
                pass

            current_amounts.extend(a[0] for a in line_amounts)
            current_codes.extend(c for c in line_codes if c not in current_codes)
            if line_date and not current_date:
                current_date = line_date

            # Extract description part (text before the first amount)
            first_amt_pos = line_amounts[0][1]
            desc_part = stripped[:first_amt_pos].strip()
            if desc_part and len(desc_part) > 2:
                current_desc_lines.append(desc_part)
        else:
            # No amounts — could be description continuation or header
            if current_amounts:
                # Flush previous item, start fresh
                desc = " ".join(current_desc_lines).strip()
                if len(desc) > 200:
                    desc = desc[:200]
                items.append({
                    "description": desc,
                    "amounts": current_amounts,
                    "codes": current_codes,
                    "service_date": current_date,
                    "amount_type": classify_amount_type(desc),
                })
                current_desc_lines = [stripped]
                current_amounts = []
                current_codes = line_codes
                current_date = line_date
            else:
                # Accumulate description
                current_desc_lines.append(stripped)
                current_codes.extend(c for c in line_codes if c not in current_codes)
                if line_date and not current_date:
                    current_date = line_date

    # Flush last item
    if current_amounts:
        desc = " ".join(current_desc_lines).strip()
        if len(desc) > 200:
            desc = desc[:200]
        items.append({
            "description": desc,
            "amounts": current_amounts,
            "codes": current_codes,
            "service_date": current_date,
            "amount_type": classify_amount_type(desc),
        })

    return items
