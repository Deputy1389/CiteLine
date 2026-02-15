"""
Step 6 — Date extraction (tiered).
Tier 1: explicit labels (date of service, encounter date, etc.)
Tier 2: header dates, "seen on" patterns.
Rejects: printed on, generated on, faxed on.
"""
from __future__ import annotations

import re
from datetime import date

from packages.shared.models import DateKind, DateSource, EventDate, Page, Warning

# Common date formats
_DATE_PATTERNS = [
    # MM/DD/YYYY or MM-DD-YYYY
    r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})",
    # YYYY-MM-DD
    r"(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})",
    # Month DD, YYYY
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
    # Mon DD, YYYY (abbreviated)
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})",
]

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

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


def _parse_date_from_match(match: re.Match, pattern_index: int) -> date | None:
    """Parse a date from a regex match based on which pattern matched."""
    try:
        groups = match.groups()
        if pattern_index == 0:  # MM/DD/YYYY
            month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
        elif pattern_index == 1:  # YYYY-MM-DD
            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
        elif pattern_index in (2, 3):  # Month DD, YYYY
            month = _MONTH_MAP.get(groups[0].lower(), 0)
            day, year = int(groups[1]), int(groups[2])
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
    for i, pattern in enumerate(_DATE_PATTERNS):
        for m in re.finditer(pattern, text, re.IGNORECASE):
            d = _parse_date_from_match(m, i)
            if d:
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
            # We want to find matches that end near the end of the context string
            for m in re.finditer(pattern, context, re.IGNORECASE):
                matches.append((m.end(), label_type))
    
    if not matches:
        return None
        
    # Sort by end position (descending) to get the one closest to the date
    matches.sort(key=lambda x: x[0], reverse=True)
    
    # The closest label wins
    return matches[0][1]


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


def extract_dates_for_pages(pages: list[Page]) -> dict[int, list[EventDate]]:
    """
    Extract dates for all pages.
    Returns {page_number: [EventDate, ...]}.
    """
    result: dict[int, list[EventDate]] = {}
    for page in pages:
        dates = [ed for ed, _ in extract_dates(page)]
        if dates:
            result[page.page_number] = dates
    return result
