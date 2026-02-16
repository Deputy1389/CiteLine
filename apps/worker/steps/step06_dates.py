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

from packages.shared.models import DateKind, DateSource, EventDate, Page, Warning

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


# ── Parsing helpers ──────────────────────────────────────────────────────


def _parse_date_from_match(match: re.Match, pattern_index: int) -> date | None:
    """Parse a date from a regex match based on which pattern matched."""
    try:
        groups = match.groups()
        if pattern_index == 0:  # MM/DD/YYYY
            month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
        elif pattern_index == 1:  # YYYY-MM-DD
            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
        elif pattern_index in (2, 3, 4, 5):  # Month DD YYYY variants
            month = _MONTH_MAP.get(groups[0].lower(), 0)
            day, year = int(groups[1]), int(groups[2])
        elif pattern_index in (6, 7):  # DD Month YYYY
            day = int(groups[0])
            month = _MONTH_MAP.get(groups[1].lower(), 0)
            year = int(groups[2])
        else:
            return None

        if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
            return date(year, month, day)
    except (ValueError, IndexError):
        pass
    return None


def _find_dates_in_text(text: str) -> list[tuple[date, int]]:
    """Find all dates in text with their character positions."""
    results: list[tuple[date, int]] = []
    seen: set[tuple[date, int]] = set()
    for i, pattern in enumerate(_DATE_PATTERNS):
        for m in re.finditer(pattern, text, re.IGNORECASE):
            d = _parse_date_from_match(m, i)
            if d:
                key = (d, m.start())
                if key not in seen:
                    seen.add(key)
                    results.append((d, m.start()))
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
    Checks all pages but prioritises earlier ones. Returns the first valid
    anchor date found.
    """
    for page in pages:
        text = page.text
        for label_pattern in _ANCHOR_LABELS:
            # Build a combined pattern: label followed by a date
            for date_idx, date_pattern in enumerate(_DATE_PATTERNS):
                combined = label_pattern + date_pattern
                m = re.search(combined, text, re.IGNORECASE)
                if m:
                    # The date groups start after the label groups (which is 0 groups)
                    # We need to extract only the date part
                    # Re-search just the date portion
                    date_match = re.search(date_pattern, text[m.start():], re.IGNORECASE)
                    if date_match:
                        d = _parse_date_from_match(date_match, date_idx)
                        if d:
                            logger.info(
                                f"Anchor date found on page {page.page_number}: {d}"
                            )
                            return d
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
            day_num = int(m.group(1))
            resolved_value: date | None = None
            
            if anchor:
                if kind == "day":
                    resolved_value = anchor + timedelta(days=max(0, day_num - 1))
                else:  # postop
                    resolved_value = anchor + timedelta(days=day_num)
            
            key = (resolved_value, day_num)
            if key not in seen_dates:
                seen_dates.add(key)
                results.append(
                    EventDate(
                        kind=DateKind.SINGLE,
                        value=resolved_value,
                        relative_day=day_num if kind == "day" else None,
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

    for d, pos in found_dates:
        # Find best label in context
        label_type = _find_best_label(text, pos)

        if label_type == "reject":
            continue

        elif label_type == "tier1":
            results.append((
                EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1),
                "tier1",
            ))

        elif label_type == "tier2":
            results.append((
                EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER2),
                "tier2",
            ))

        else:
            # No label found. Check heuristics.
            # Unlabeled date at top of page → tier 2 (header date)
            if pos < len(text) * 0.2:
                results.append((
                    EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER2),
                    "header_date",
                ))

    return results


# ── Multi-page extraction with propagation ───────────────────────────────


def extract_dates_for_pages(pages: list[Page]) -> dict[int, list[EventDate]]:
    """
    Extract dates for all pages with multi-layer resolution.
    Returns {page_number: [EventDate, ...]}.

    Resolution order:
      1. Per-page regex extraction (tier 1 / tier 2)
      2. Relative date resolution (absolute if anchor found, else relative)
      3. Header propagation from the previous page in the same document
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

        # Resolve relative dates on pages that are still missing dates
        # OR add relative dates as secondary info?
        # Current logic: only if page missing dates? 
        # Better: extract relative dates everywhere, merge?
        # For now, stick to "fill gaps" strategy but enable it even if no date found yet
        for page in doc_page_list:
            if page.page_number not in result:
                resolved = _resolve_relative_dates(page, anchor)
                if resolved:
                    result[page.page_number] = resolved
                    
                    if anchor:
                         logger.debug(
                            f"Resolved absolute date on page {page.page_number}: "
                            f"{resolved[0].value}"
                        )
                    else:
                        logger.debug(
                            f"Extracted relative date on page {page.page_number}: "
                            f"Day {resolved[0].relative_day}"
                        )

    # ── Pass 3: header propagation ───────────────────────────────────────
    for doc_id, doc_page_list in doc_pages.items():
        last_valid_date: EventDate | None = None

        for page in doc_page_list:
            if page.page_number in result:
                # This page has dates — update the propagation source
                # Prefer one with a Value if possible
                candidates = result[page.page_number]
                best_candidate = candidates[0]
                for c in candidates:
                    if c.value is not None:
                        best_candidate = c
                        break
                last_valid_date = best_candidate
            elif last_valid_date is not None:
                # No dates on this page — propagate from previous
                propagated = EventDate(
                    kind=DateKind.SINGLE,
                    value=last_valid_date.value,
                    relative_day=last_valid_date.relative_day,
                    source=DateSource.PROPAGATED,
                )
                result[page.page_number] = [propagated]
                val_str = str(propagated.value) if propagated.value else f"Day {propagated.relative_day}"
                logger.debug(
                    f"Propagated date to page {page.page_number}: {val_str}"
                )

    return result
