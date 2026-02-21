
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import timedelta
from packages.shared.models import Page, PageType, EventDate, Provider

CLINICAL_TYPES = {PageType.CLINICAL_NOTE, PageType.OPERATIVE_REPORT, PageType.DISCHARGE_SUMMARY}

@dataclass
class ClinicalBlock:
    pages: list[Page] = field(default_factory=list)
    primary_date: EventDate | None = None
    primary_provider_id: str | None = None

    @property
    def page_numbers(self) -> list[int]:
        return [p.page_number for p in self.pages]

def group_clinical_pages(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str]
) -> list[ClinicalBlock]:
    """
    Group contiguous clinical pages into blocks.
    Breaks on:
    - Non-clinical page
    - Page gap > 1
    - Different source document
    - Strong date mismatch (>1 day)
    - Defined provider mismatch
    """
    # 1. Filter and sort
    relevant_pages = sorted(
        [p for p in pages if p.page_type in CLINICAL_TYPES],
        key=lambda p: (p.source_document_id, p.page_number)
    )
    
    if not relevant_pages:
        return []

    blocks: list[ClinicalBlock] = []
    current_block: ClinicalBlock | None = None

    import logging
    logger = logging.getLogger(__name__)

    for page in relevant_pages:
        # Get metadata for this page
        page_date = _get_best_date(dates.get(page.page_number, []))
        page_prov_id = page_provider_map.get(page.page_number)
        
        if current_block is None:
            current_block = _start_block(page, page_date, page_prov_id)
            continue
            
        # Check continuity
        prev_page = current_block.pages[-1]
        
        # 1. Document boundary
        if page.source_document_id != prev_page.source_document_id:
            logger.info(f"Grouping Split: Doc ID mismatch {page.page_number}")
            blocks.append(current_block)
            current_block = _start_block(page, page_date, page_prov_id)
            continue
            
        # 2. Page gap (must be strictly contiguous n, n+1)
        if page.page_number != prev_page.page_number + 1:
            logger.info(f"Grouping Split: Page gap {prev_page.page_number}->{page.page_number}")
            blocks.append(current_block)
            current_block = _start_block(page, page_date, page_prov_id)
            continue
            
        # 3. Date mismatch (if both present)
        if current_block.primary_date and page_date:
            if not _dates_compatible(current_block.primary_date, page_date):
                logger.info(f"Grouping Split: Date mismatch {current_block.primary_date.value} vs {page_date.value}")
                blocks.append(current_block)
                current_block = _start_block(page, page_date, page_prov_id)
                continue
        elif not current_block.primary_date and page_date:
            # Adopt date if block had none
            current_block.primary_date = page_date

        # 4. Provider mismatch (if both present)
        # Only break if both explicitly detected and different
        if current_block.primary_provider_id and page_prov_id:
             if current_block.primary_provider_id != page_prov_id:
                logger.info(f"Grouping Split: Provider mismatch {current_block.primary_provider_id} vs {page_prov_id}")
                blocks.append(current_block)
                current_block = _start_block(page, page_date, page_prov_id)
                continue
        elif not current_block.primary_provider_id and page_prov_id:
             current_block.primary_provider_id = page_prov_id

        # Compatible - add to block
        current_block.pages.append(page)
    
    if current_block:
        blocks.append(current_block)
        
    return blocks

def _start_block(page: Page, date: EventDate | None, prov: str | None) -> ClinicalBlock:
    return ClinicalBlock(
        pages=[page],
        primary_date=date,
        primary_provider_id=prov
    )

def _get_best_date(page_dates: list[EventDate]) -> EventDate | None:
    if not page_dates:
        return None
    # Prefer TIER1 (explicit label)
    tier1 = [d for d in page_dates if d.source == "tier1"]
    if tier1:
        return tier1[0]
    return page_dates[0]

def _dates_compatible(d1: EventDate, d2: EventDate) -> bool:
    """True if dates are within 1 day of each other."""
    # Simplify: compare sort_date strings or objects
    # d1.value might be string or dict (range)
    # Let's extract a comparable date object
    dt1 = _parse_date(d1)
    dt2 = _parse_date(d2)
    
    if not dt1 or not dt2:
        return True # Can't compare, assume compatible
        
    diff = abs(dt1 - dt2)
    return diff <= timedelta(days=1)

def _parse_date(ed: EventDate):
    from datetime import date
    val = ed.value
    if isinstance(val, dict):
        # Use start of range
        val = val.get("start")
    
    if not val:
        return None
        
    try:
        # It's a string in YYYY-MM-DD format
        return date.fromisoformat(str(val))
    except ValueError:
        return None
