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
    SkippedEvent,
    Warning,
)
from .common import _make_citation, _make_fact

def _extract_amount(text: str) -> float | None:
    """Extract a dollar amount from text."""
    patterns = [
        r"total\s*(?:due|amount|charges|billed|balance)?\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        r"balance\s*(?:due|owed|remaining)?\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        r"amount\s*(?:due|owed|billed)?\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        r"charges?\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        r"billed\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        r"\$\s*([\d,]+\.?\d*)",  # Generic dollar amount (last resort)
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                amount = float(m.group(1).replace(",", ""))
                # Sanity check: billing amounts usually > $1 and < $1M
                if 1.0 <= amount <= 1000000.0:
                    return amount
            except ValueError:
                continue
    return None

def extract_billing_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str] = {},
) -> tuple[list[Event], list[Citation], list[Warning], list[SkippedEvent]]:
    """Extract billing events (always stored; export based on config)."""
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[Warning] = []
    skipped: list[SkippedEvent] = []

    billing_pages = [p for p in pages if p.page_type == PageType.BILLING]

    for page in billing_pages:
        event_flags: list[str] = []
        page_dates = dates.get(page.page_number, [])
        text_lower = page.text.lower()

        amount = _extract_amount(page.text)

        # Expanded triggers: Even if no amount, check for billing indicators
        billing_indicators = [
            "statement", "invoice", "bill", "charges", "payment", "balance",
            "insurance", "cpt", "icd", "procedure code", "diagnosis code",
            "patient account", "account number", "date of service", "claim"
        ]

        indicator_count = sum(1 for indicator in billing_indicators if indicator in text_lower)

        if amount is None and indicator_count < 2:
            # No amount and not enough billing indicators
            skipped.append(SkippedEvent(
                page_numbers=[page.page_number],
                reason_code="NO_TRIGGER_MATCH",
                snippet=page.text[:250].strip()[:300],
            ))
            continue

        event_date = page_dates[0] if page_dates else None
        if not event_date:
            warnings.append(Warning(
                 code="MISSING_DATE",
                 message=f"Billing event for page {page.page_number} has no resolved date",
                 page=page.page_number
            ))
            event_flags.append("MISSING_DATE")
        
        # Determine provider
        provider_id = page_provider_map.get(page.page_number)
        if not provider_id and providers:
            provider_id = providers[0].provider_id
        provider_id = provider_id or "unknown"

        if amount is not None:
            snippet = f"Total amount: ${amount:.2f}"
        else:
            snippet = "Billing record detected (amount not specified)"
            event_flags.append("NO_AMOUNT")

        cit = _make_citation(page, snippet)
        citations.append(cit)

        has_cpt = bool(re.search(r"\b\d{5}\b", text_lower))  # 5-digit codes
        has_icd = bool(re.search(r"\b[a-z]\d{2}\.?\d*\b", text_lower))
        line_items = len(re.findall(r"\n\s*\d+\s+", page.text))

        # Only build BillingDetails when we have a date for statement_date
        billing = None
        if event_date:
            billing = BillingDetails(
                statement_date=event_date.sort_date(),
                total_amount=amount if amount is not None else 0.0,
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
            flags=event_flags,
            citation_ids=[cit.citation_id],
            source_page_numbers=[page.page_number],
        ))

    return events, citations, warnings, skipped
