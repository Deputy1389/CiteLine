from __future__ import annotations
import re
import uuid
from packages.shared.models import (
    BillingDetails,
    Citation,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Page,
    PageType,
    Provider,
    Warning,
)
from .common import _make_citation, _make_fact

def _extract_amount(text: str) -> float | None:
    """Extract a dollar amount from text."""
    patterns = [
        r"\$\s*([\d,]+\.?\d*)",
        r"total\s*(?:due|amount|charges)?\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        r"balance\s*(?:due)?\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        r"amount\s*(?:due)?\s*:?\s*\$?\s*([\d,]+\.?\d*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None

def extract_billing_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str] = {},
) -> tuple[list[Event], list[Citation], list[Warning]]:
    """Extract billing events (always stored; export based on config)."""
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []

    billing_pages = [p for p in pages if p.page_type == PageType.BILLING]

    for page in billing_pages:
        page_dates = dates.get(page.page_number, [])
        if not page_dates:
            continue

        amount = _extract_amount(page.text)
        if amount is None:
            continue

        event_date = page_dates[0]
        
        # Determine provider
        provider_id = page_provider_map.get(page.page_number)
        if not provider_id and providers:
            provider_id = providers[0].provider_id
        provider_id = provider_id or "unknown"
        text_lower = page.text.lower()

        snippet = f"Total amount: ${amount:.2f}"
        cit = _make_citation(page, snippet)
        citations.append(cit)

        has_cpt = bool(re.search(r"\b\d{5}\b", text_lower))  # 5-digit codes
        has_icd = bool(re.search(r"\b[a-z]\d{2}\.?\d*\b", text_lower))
        line_items = len(re.findall(r"\n\s*\d+\s+", page.text))

        billing = BillingDetails(
            statement_date=event_date.sort_date(),
            total_amount=amount,
            currency="USD",
            line_item_count=max(line_items, 0),
            has_cpt_codes=has_cpt,
            has_icd_codes=has_icd,
        )

        events.append(Event(
            event_id=uuid.uuid4().hex[:16],
            provider_id=provider_id,
            event_type=EventType.BILLING_EVENT,
            date=event_date,
            facts=[_make_fact(snippet, FactKind.OTHER, cit.citation_id)],
            billing=billing,
            confidence=0,
            citation_ids=[cit.citation_id],
            source_page_numbers=[page.page_number],
        ))

    return events, citations, warnings
