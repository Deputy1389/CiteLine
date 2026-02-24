"""
Step 6 — Date extraction (tiered, multi-layer).

Tier 1: explicit labels (date of service, encounter date, etc.)
Tier 2: header dates, "seen on" patterns.
Anchor: anchor dates (admission date) + relative offsets ("Day 2").
Propagated: inherited from the previous page in the same document.
Rejects: printed on, generated on, faxed on.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, timedelta

from packages.shared.models import DateKind, DateSource, DateStatus, EventDate, DateRange, Page, Warning, PageType

logger = logging.getLogger(__name__)

# ── Date regex patterns ──────────────────────────────────────────────────

_FULL_MONTHS = (
    "January|February|March|April|May|June|July|August"
    "|September|October|November|December"
)
_ABBREV_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"

_DATE_PATTERNS = [
    # 0: MM/DD/YYYY or MM-DD-YYYY
    r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})",
    # 1: YYYY-MM-DD
    r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})",
    # 2: Month DD, YYYY  (e.g. March 14, 2024)
    rf"({_FULL_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})",
    # 3: Mon DD, YYYY  (e.g. Mar 14, 2024)
    rf"({_ABBREV_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})",
    # 4: Month DDth, YYYY  (ordinal — e.g. March 14th, 2024)
    rf"({_FULL_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th),?\s+(\d{{4}})",
    # 5: Mon DDth, YYYY  (ordinal abbreviated — e.g. Mar 14th, 2024)
    rf"({_ABBREV_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th),?\s+(\d{{4}})",
    # 6: DD Month YYYY  (e.g. 14 March 2024)
    rf"(\d{{1,2}})\s+({_FULL_MONTHS}),?\s+(\d{{4}})",
    # 7: DD Mon YYYY  (e.g. 14 Mar 2024)
    rf"(\d{{1,2}})\s+({_ABBREV_MONTHS}),?\s+(\d{{4}})",
    # 8: MM/DD/YY (2-digit year)
    r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})\b",
    # 9: DDth of Month, YYYY (e.g. 14th of March, 2024)
    rf"(\d{{1,2}})(?:st|nd|rd|th)\s+of\s+({_FULL_MONTHS}),?\s+(\d{{4}})",
]

_DATE_RANGE_PATTERNS = [
    # "From MM/DD/YYYY to MM/DD/YYYY"
    rf"(?i)from\s+({_DATE_PATTERNS[0]})\s+to\s+({_DATE_PATTERNS[0]})",
    # "Between MM/DD/YYYY and MM/DD/YYYY"
    rf"(?i)between\s+({_DATE_PATTERNS[0]})\s+and\s+({_DATE_PATTERNS[0]})",
    # "MM/YYYY - MM/YYYY" (Service range)
    r"(\d{1,2})[/\-](\d{4})\s*[\-–—]\s*(\d{1,2})[/\-](\d{4})",
]

_PARTIAL_DATE_PATTERNS = [
    # 0: Month DD (e.g. September 24)
    rf"({_FULL_MONTHS})\s+(\d{{1,2}})(?!\s*,\s*\d{{4}})(?!\s+\d{{4}})",
    # 1: Mon DD (e.g. Sep 24)
    rf"({_ABBREV_MONTHS})\s+(\d{{1,2}})(?!\s*,\s*\d{{4}})(?!\s+\d{{4}})",
    # 2: MM/DD (e.g. 09/24)
    r"(\d{1,2})/(\d{1,2})(?![/\-]\d{2,4})",
]

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

# ── Label patterns ───────────────────────────────────────────────────────

# Tier 1 labels (highest confidence)
_TIER1_LABELS = [
    r"date of service\s*:?\s*",
    r"dos\s*:?\s*",
    r"encounter date\s*:?\s*",
    r"visit date\s*:?\s*",
    r"exam date\s*:?\s*",
    r"study date\s*:?\s*",
    r"admit date\s*:?\s*",
    r"admission date\s*:?\s*",
    r"discharge date\s*:?\s*",
    r"date of injury\s*:?\s*",
    r"service date\s*:?\s*",
    r"date of exam\s*:?\s*",
    r"date of procedure\s*:?\s*",
    r"procedure date\s*:?\s*",
    r"surgery date\s*:?\s*",
    r"statement date\s*:?\s*",
]

# Tier 2 labels
_TIER2_LABELS = [
    r"date\s*:?\s*",
    r"seen on\s*:?\s*",
    r"report date\s*:?\s*",
]

# Reject labels (not event dates)
_REJECT_LABELS = [
    r"printed on\s*:?\s*",
    r"generated on\s*:?\s*",
    r"faxed on\s*:?\s*",
    r"fax date\s*:?\s*",
    r"created on\s*:?\s*",
    r"print date\s*:?\s*",
]

# ── Anchor date labels ───────────────────────────────────────────────────

_ANCHOR_LABELS = [
    r"admission date\s*:?\s*",
    r"admit date\s*:?\s*",
    r"date admitted\s*:?\s*",
    r"date of admission\s*:?\s*",
    r"service date\s*:?\s*",
    r"encounter date\s*:?\s*",
    r"visit date\s*:?\s*",
    r"date of service\s*:?\s*",
    r"dos\s*:?\s*",
]

# ── Relative date patterns ───────────────────────────────────────────────

_RELATIVE_PATTERNS = [
    # More specific patterns first to avoid shorter pattern stealing the match
    # "Hospital Day 3"
    (r"\bhospital\s+day\s+(\d{1,3})\b", "day"),
    # "Post-op Day 1", "POD 1"
    (r"\bpost-?op\s+day\s+(\d{1,3})\b", "postop"),
    (r"\bPOD\s+(\d{1,3})\b", "postop"),
    # "Day 1", "Day 2, 0900", "Day 1:" — generic, must be last
    (r"(?<!hospital\s)(?<!op\s)\bday\s+(\d{1,3})\b", "day"),
]


def make_partial_date(month: int, day: int) -> EventDate:
    return EventDate(
        kind=DateKind.SINGLE,
        value=None,
        relative_day=None,  # STRICTLY None for partials
        source=DateSource.TIER2,
        partial_month=month,
        partial_day=day,
        extensions={
            "partial_date": True,
            "partial_month": month,
            "partial_day": day,
            "year_missing": True,
        },
    )


def is_copyright_or_footer_context(line: str) -> bool:
    s = line.lower()
    blocklist = [
        "©",
        "national league for nursing",
        "chart materials",
        "copyright",
        "all rights reserved",
    ]
    return any(b in s for b in blocklist)


# ── Parsing helpers ──────────────────────────────────────────────────────


def _parse_date_from_match(match: re.Match, pattern_index: int) -> date | None:
    """Parse a date from a regex match based on which pattern matched."""
    try:
        groups = match.groups()
        if pattern_index == 0 or pattern_index == 8:  # MM/DD/YYYY or MM/DD/YY
            month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
            if pattern_index == 8 and year < 100:
                year += 2000 if year < 50 else 1900
        elif pattern_index == 1:  # YYYY-MM-DD
            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
        elif pattern_index in (2, 3, 4, 5):  # Month DD YYYY variants
            month = _MONTH_MAP.get(groups[0].lower(), 0)
            day, year = int(groups[1]), int(groups[2])
        elif pattern_index in (6, 7):  # DD Month YYYY
            day = int(groups[0])
            month = _MONTH_MAP.get(groups[1].lower(), 0)
            year = int(groups[2])
        elif pattern_index == 9:  # DDth of Month YYYY
            day = int(groups[0])
            month = _MONTH_MAP.get(groups[1].lower(), 0)
            year = int(groups[2])
        else:
            return None

        if 1 <= month <= 12 and 1 <= day <= 31 and 1990 <= year <= 2200:
            return date(year, month, day)
    except (ValueError, IndexError):
        pass
    return None


def _find_dates_in_text(text: str) -> list[tuple[date, int, int]]:
    """Find all dates in text with their character positions and line numbers."""
    results: list[tuple[date, int, int]] = []
    seen: set[tuple[date, int]] = set()
    
    # Split by lines to check context
    lines = text.split("\n")
    current_pos = 0
    
    for line_idx, line in enumerate(lines):
        if is_copyright_or_footer_context(line):
            current_pos += len(line) + 1
            continue
            
        for i, pattern in enumerate(_DATE_PATTERNS):
            for m in re.finditer(pattern, line, re.IGNORECASE):
                d = _parse_date_from_match(m, i)
                if d:
                    pos = current_pos + m.start()
                    key = (d, pos)
                    if key not in seen:
                        seen.add(key)
                        results.append((d, pos, line_idx + 1))
        current_pos += len(line) + 1
        
    return results


def _parse_range_from_match(match: re.Match, pattern_index: int) -> DateRange | None:
    try:
        groups = match.groups()
        if pattern_index in (0, 1):  # From/Between
            # groups are (m1, d1, y1, m2, d2, y2)
            d1 = date(int(groups[2]), int(groups[0]), int(groups[1]))
            d2 = date(int(groups[5]), int(groups[3]), int(groups[4]))
            return DateRange(start=d1, end=d2)
        elif pattern_index == 2:  # MM/YYYY - MM/YYYY
            # groups are (m1, y1, m2, y2)
            d1 = date(int(groups[1]), int(groups[0]), 1)
            # End of month for d2
            y2, m2 = int(groups[3]), int(groups[2])
            import calendar
            _, last_day = calendar.monthrange(y2, m2)
            d2 = date(y2, m2, last_day)
            return DateRange(start=d1, end=d2)
    except (ValueError, IndexError):
        pass
    return None


def _find_date_ranges_in_text(text: str) -> list[tuple[DateRange, int, int]]:
    results: list[tuple[DateRange, int, int]] = []
    lines = text.split("\n")
    current_pos_val = 0
    for line_idx, line in enumerate(lines):
        for i, pattern in enumerate(_DATE_RANGE_PATTERNS):
            for m in re.finditer(pattern, line, re.IGNORECASE):
                dr = _parse_range_from_match(m, i)
                if dr:
                    results.append((dr, current_pos_val + m.start(), line_idx + 1))
        current_pos_val += len(line) + 1
    return results


def _find_best_label(text: str, date_pos: int) -> str | None:
    """
    Find the closest label preceding the date within a context window.
    Returns: 'reject', 'tier1', 'tier2', or None.
    """
    window_size = 80
    start = max(0, date_pos - window_size)
    context = text[start:date_pos]

    matches: list[tuple[int, str]] = []  # (end_pos, type)

    # Check all label groups
    for labels, label_type in [
        (_REJECT_LABELS, "reject"),
        (_TIER1_LABELS, "tier1"),
        (_TIER2_LABELS, "tier2"),
    ]:
        for pattern in labels:
            for m in re.finditer(pattern, context, re.IGNORECASE):
                matches.append((m.end(), label_type))

    if not matches:
        return None

    # Sort by end position (descending) to get the one closest to the date
    matches.sort(key=lambda x: x[0], reverse=True)

    # The closest label wins
    return matches[0][1]


# ── Anchor date detection ────────────────────────────────────────────────


def _find_anchor_date(pages: list[Page]) -> date | None:
    """
    Scan pages for a labeled anchor date (e.g. "Admission Date: 01/15/2024").
    Checks all pages but prioritises earlier ones.
    Fallback: returns the first valid date found on any page if no labeled anchor exists.
    """
    first_detected_date: date | None = None

    for page in pages:
        text = page.text
        # First, try labeled anchor patterns
        for label_pattern in _ANCHOR_LABELS:
            for date_idx, date_pattern in enumerate(_DATE_PATTERNS):
                combined = label_pattern + date_pattern
                m = re.search(combined, text, re.IGNORECASE)
                if m:
                    date_match = re.search(date_pattern, text[m.start():], re.IGNORECASE)
                    if date_match:
                        d = _parse_date_from_match(date_match, date_idx)
                        if d:
                            logger.info(f"Anchor date found on page {page.page_number}: {d}")
                            return d
        
        # Second, keep track of the first date we see anywhere (as a fallback)
        if first_detected_date is None:
            raw_dates = _find_dates_in_text(text)
            if raw_dates:
                # Use the one closest to top of page
                raw_dates.sort(key=lambda x: x[1])
                first_detected_date = raw_dates[0][0]

    if first_detected_date:
        logger.info(f"Using fallback anchor date from body text: {first_detected_date}")
        return first_detected_date

    return None


# ── Relative date resolution ─────────────────────────────────────────────


def _resolve_relative_dates(page: Page, anchor: date | None) -> list[EventDate]:
    """
    Detect relative date patterns ("Day 1", "Hospital Day 3", "Post-op Day 2").
    If anchor is provided, resolves to absolute date.
    If no anchor, returns EventDate with relative_day set.

    Day X    → anchor + (X - 1) days  (Day 1 = anchor date itself)
    POD X    → anchor + X days        (Post-op Day 0 = surgery day)
    """
    results: list[EventDate] = []
    seen_dates: set[tuple[date | None, int | None]] = set()

    for pattern, kind in _RELATIVE_PATTERNS:
        for m in re.finditer(pattern, page.text, re.IGNORECASE):
            try:
                day_num = int(m.group(1))
            except (ValueError, IndexError):
                continue

            resolved_value: date | None = None
            if anchor:
                try:
                    if kind == "day":
                        resolved_value = anchor + timedelta(days=max(0, day_num - 1))
                    else:  # postop
                        resolved_value = anchor + timedelta(days=day_num)
                except Exception:
                    pass
            
            # Only emit if we could resolve to a real date.
            # An EventDate(value=None) passes `if event.date:` checks but then
            # breaks any code that tries to format or sort on the date value.
            if resolved_value:
                key = (resolved_value, day_num)
                if key not in seen_dates:
                    seen_dates.add(key)
                    results.append(
                        EventDate(
                            kind=DateKind.SINGLE,
                            value=resolved_value,
                            relative_day=day_num,
                            source=DateSource.ANCHOR if anchor else DateSource.TIER2,
                        )
                    )

    return results


# ── Core per-page extraction ─────────────────────────────────────────────


def extract_dates(page: Page) -> list[tuple[EventDate, str]]:
    """
    Extract dates from a page with tier classification.
    Returns list of (EventDate, label_matched).
    """
    text = page.text
    results: list[tuple[EventDate, str]] = []
    found_dates = _find_dates_in_text(text)

    for d, pos, line_num in found_dates:
        # Find best label in context
        label_type = _find_best_label(text, pos)

        if label_type == "reject":
            continue

        elif label_type == "tier1":
            results.append((
                EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1, line_number=line_num, status=DateStatus.EXPLICIT),
                "tier1",
            ))

        elif label_type == "tier2":
            results.append((
                EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER2, line_number=line_num, status=DateStatus.EXPLICIT),
                "tier2",
            ))

        else:
            # No label found. Check heuristics.
            # Unlabeled date at top of page → tier 2 (header date)
            if pos < len(text) * 0.2:
                results.append((
                    EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER2, line_number=line_num, status=DateStatus.PROPAGATED),
                    "header_date",
                ))

    # Second pass: Date Ranges
    ranges = _find_date_ranges_in_text(text)
    for dr, pos, line_num in ranges:
        results.append((
            EventDate(kind=DateKind.RANGE, value=dr, source=DateSource.TIER2, line_number=line_num, status=DateStatus.RANGE),
            "range",
        ))

    # Third pass: Partial dates
    partials = _find_partial_dates_in_text_with_lines(text)
    for month, day, pos, line_num in partials:
        # Check if we already covered this position with a full date
        if any(abs(pos - p) < 5 for _, p, _ in found_dates):
            continue

        label_type = _find_best_label(text, pos)
        if label_type == "reject":
            continue

        # Store partials as EventDates using explicit partial fields and extensions.
        ed = make_partial_date(month, day)
        ed.line_number = line_num
        ed.status = DateStatus.AMBIGUOUS
        results.append((ed, "partial"))

    return results


def _find_partial_dates_in_text_with_lines(text: str) -> list[tuple[int, int, int, int]]:
    results: list[tuple[int, int, int, int]] = []
    lines = text.split("\n")
    current_pos = 0
    for line_idx, line in enumerate(lines):
        for i, pattern in enumerate(_PARTIAL_DATE_PATTERNS):
            for m in re.finditer(pattern, line, re.IGNORECASE):
                try:
                    groups = m.groups()
                    if i in (0, 1):  # Month DD
                        month = _MONTH_MAP.get(groups[0].lower(), 0)
                        day = int(groups[1])
                    else:  # MM/DD
                        month, day = int(groups[0]), int(groups[1])

                    if 1 <= month <= 12 and 1 <= day <= 31:
                        results.append((month, day, current_pos + m.start(), line_idx + 1))
                except Exception:
                    continue
        current_pos += len(line) + 1
    return results


# ── Multi-page extraction with propagation ───────────────────────────────


def extract_dates_for_pages(
    pages: list[Page], 
    page_provider_map: dict[int, str] = {}
) -> dict[int, list[EventDate]]:
    """
    Extract dates for all pages with multi-layer resolution.
    Returns {page_number: [EventDate, ...]}.

    Resolution order:
      1. Per-page regex extraction (tier 1 / tier 2)
      2. Relative date resolution (absolute if anchor found, else relative)
      3. Header propagation from the previous page in the same document
      4. Provider-session propagation (New: Bug 3A)
    """
    result: dict[int, list[EventDate]] = {}

    # ── Pass 1: per-page regex extraction ────────────────────────────────
    for page in pages:
        dates = [ed for ed, _ in extract_dates(page)]
        if dates:
            result[page.page_number] = dates

    # ── Pass 2: anchor detection + relative date resolution ──────────────
    # Group pages by source document for isolation
    doc_pages: dict[str, list[Page]] = defaultdict(list)
    for page in pages:
        doc_pages[page.source_document_id].append(page)

    for doc_id, doc_page_list in doc_pages.items():
        # Sort pages by page number within each document
        doc_page_list.sort(key=lambda p: p.page_number)

        # Try to find an anchor date from this document's pages
        anchor = _find_anchor_date(doc_page_list)

        for page in doc_page_list:
            if page.page_number not in result:
                resolved = _resolve_relative_dates(page, anchor)
                if resolved:
                    result[page.page_number] = resolved

    # ── Pass 3: Year Inference & Header propagation ───────────────────────
    for doc_id, doc_page_list in doc_pages.items():
        last_valid_date: EventDate | None = None
        
        # Determine anchor year for this document
        anchor_year = None
        for p in doc_page_list:
            if p.page_number in result:
                for ed in result[p.page_number]:
                    if ed.value and isinstance(ed.value, date):
                        anchor_year = ed.value.year
                        break
            if anchor_year: break

        for page in doc_page_list:
            if page.page_number in result:
                # 1. Resolve partials if possible
                for ed in result[page.page_number]:
                    if ed.value is None and ed.partial_month is not None:
                        pass
                
                # Update propagation source
                candidates = result[page.page_number]
                best_candidate = candidates[0]
                for c in candidates:
                    if c.value is not None:
                        best_candidate = c
                        break
                last_valid_date = best_candidate
            elif last_valid_date is not None:
                # ── DOI Propagation Ban (Clause V) ──
                # Billing, PT, and Summary pages should NOT anchor to the DOI header.
                # If they have no date, they are UNDATED.
                _BAN_TYPES = (PageType.PT_NOTE, PageType.BILLING, PageType.DISCHARGE_SUMMARY)
                if page.page_type in _BAN_TYPES:
                    propagated = EventDate(
                        kind=DateKind.SINGLE,
                        value=None,
                        source=DateSource.PROPAGATED,
                        status=DateStatus.UNDATED,
                    )
                else:
                    propagated = EventDate(
                        kind=DateKind.SINGLE,
                        value=last_valid_date.value,
                        relative_day=last_valid_date.relative_day,
                        source=DateSource.PROPAGATED,
                        status=DateStatus.PROPAGATED,
                    )
                result[page.page_number] = [propagated]

    # ── Pass 4: Provider-session propagation (Bug 3A) ─────────────────────
    # If a provider has multiple pages in a cluster, they should likely share 
    # the same date even if some pages in the middle are undated.
    if page_provider_map:
        provider_pages = defaultdict(list)
        for page in pages:
            pid = page_provider_map.get(page.page_number)
            if pid:
                provider_pages[pid].append(page)
        
        for pid, p_list in provider_pages.items():
            # Sort by page number to find clusters
            p_list.sort(key=lambda p: p.page_number)
            
            # Find the best date in this provider's pages
            best_provider_date = None
            for p in p_list:
                p_dates = result.get(p.page_number, [])
                for ed in p_dates:
                    if ed.value and ed.status != DateStatus.UNDATED:
                        best_provider_date = ed
                        break
                if best_provider_date:
                    break
            
            if best_provider_date:
                for p in p_list:
                    # If page is undated or only has a partial/ambiguous date,
                    # propagate the provider's session date.
                    p_dates = result.get(p.page_number, [])
                    is_undated = not p_dates or all(d.status == DateStatus.UNDATED for d in p_dates)
                    
                    if is_undated:
                        propagated = EventDate(
                            kind=DateKind.SINGLE,
                            value=best_provider_date.value,
                            relative_day=best_provider_date.relative_day,
                            source=DateSource.PROPAGATED,
                            status=DateStatus.PROPAGATED,
                            extensions={"provider_session_prop": True}
                        )
                        result[page.page_number] = [propagated]

    return result
