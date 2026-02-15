
import pytest
from apps.worker.lib.grouping import group_clinical_pages
from packages.shared.models import Page, PageType, EventDate

def test_grouping_integration():
    """
    Test that grouping logic reduces multiple pages to single events correctly.
    This simulates the data flow in step07_events.py.
    """
    # Create 5 pages:
    # 1-3: Clinical, same date -> Block 1
    # 4: Imaging -> Ignored by clinical grouper
    # 5-6: Clinical, diff date -> Block 2
    
    pages = [
        Page(page_id="p1", source_document_id="d1", page_number=1, text="text", text_source="ocr", page_type=PageType.CLINICAL_NOTE),
        Page(page_id="p2", source_document_id="d1", page_number=2, text="text", text_source="ocr", page_type=PageType.CLINICAL_NOTE),
        Page(page_id="p3", source_document_id="d1", page_number=3, text="text", text_source="ocr", page_type=PageType.CLINICAL_NOTE),
        Page(page_id="p4", source_document_id="d1", page_number=4, text="text", text_source="ocr", page_type=PageType.IMAGING_REPORT),
        Page(page_id="p5", source_document_id="d1", page_number=5, text="text", text_source="ocr", page_type=PageType.CLINICAL_NOTE),
        Page(page_id="p6", source_document_id="d1", page_number=6, text="text", text_source="ocr", page_type=PageType.CLINICAL_NOTE),
    ]
    
    dates = {
        1: [EventDate(kind="single", value="2023-01-01", source="tier1")],
        2: [EventDate(kind="single", value="2023-01-01", source="tier1")],
        3: [], # Missing date, should inherit
        5: [EventDate(kind="single", value="2023-02-01", source="tier1")],
        6: [EventDate(kind="single", value="2023-02-01", source="tier1")],
    }
    
    blocks = group_clinical_pages(pages, dates, [], {})
    
    assert len(blocks) == 2
    
    # Block 1: Pages 1, 2, 3
    assert blocks[0].page_numbers == [1, 2, 3]
    from datetime import date
    assert blocks[0].primary_date.value == date(2023, 1, 1)
    
    # Block 2: Pages 5, 6
    assert blocks[1].page_numbers == [5, 6]
    assert blocks[1].primary_date.value == date(2023, 2, 1)
