
import pytest
from datetime import date
from packages.shared.models import Page, PageType, EventDate, Provider
from apps.worker.lib.grouping import group_clinical_pages

def mk_page(num, ptype=PageType.CLINICAL_NOTE, doc="doc1"):
    return Page(
        page_id=f"p{num}",
        source_document_id=doc,
        page_number=num,
        text="text",
        text_source="ocr",
        page_type=ptype
    )

def mk_date(d_str):
    return EventDate(kind="single", value=d_str, source="tier1")

def test_grouping_basic():
    # p1, p2, p3 all clinical, same doc, contiguous -> 1 block
    pages = [mk_page(1), mk_page(2), mk_page(3)]
    dates = {1: [mk_date("2023-01-01")]}
    providers = []
    pmap = {}
    
    blocks = group_clinical_pages(pages, dates, providers, pmap)
    assert len(blocks) == 1
    assert blocks[0].page_numbers == [1, 2, 3]
    # The value is parsed as date object by Pydantic or our mock is behaving like one?
    # Actually mk_date created it with a string but Pydantic might have parsed it.
    # The error message shows it is a date object.
    assert blocks[0].primary_date.value == date(2023, 1, 1)

def test_grouping_break_on_type():
    # p1 clinical, p2 imaging, p3 clinical -> 2 blocks (p1), (p3)
    pages = [
        mk_page(1, PageType.CLINICAL_NOTE),
        mk_page(2, PageType.IMAGING_REPORT),
        mk_page(3, PageType.CLINICAL_NOTE)
    ]
    blocks = group_clinical_pages(pages, {}, [], {})
    assert len(blocks) == 2
    assert blocks[0].page_numbers == [1]
    assert blocks[1].page_numbers == [3]

def test_grouping_break_on_date_mismatch():
    # p1 date A, p2 date B (diff > 1 day) -> 2 blocks
    pages = [mk_page(1), mk_page(2)]
    dates = {
        1: [mk_date("2023-01-01")],
        2: [mk_date("2023-01-05")] # > 1 day gap
    }
    blocks = group_clinical_pages(pages, dates, [], {})
    assert len(blocks) == 2
    assert blocks[0].primary_date.value == date(2023, 1, 1)
    assert blocks[1].primary_date.value == date(2023, 1, 5)

def test_grouping_allow_small_date_gap():
    # p1 Jan 1, p2 Jan 2 -> 1 block (<= 1 day gap)
    pages = [mk_page(1), mk_page(2)]
    dates = {
        1: [mk_date("2023-01-01")],
        2: [mk_date("2023-01-02")]
    }
    blocks = group_clinical_pages(pages, dates, [], {})
    assert len(blocks) == 1
    assert blocks[0].page_numbers == [1, 2]

def test_grouping_break_on_provider():
    # p1 prov A, p2 prov B -> 2 blocks
    pages = [mk_page(1), mk_page(2)]
    pmap = {
        1: "provA",
        2: "provB"
    }
    blocks = group_clinical_pages(pages, {}, [], pmap)
    assert len(blocks) == 2
    assert blocks[0].primary_provider_id == "provA"
    assert blocks[1].primary_provider_id == "provB"

def test_grouping_break_on_gap():
    # p1, p3 -> 2 blocks
    pages = [mk_page(1), mk_page(3)]
    blocks = group_clinical_pages(pages, {}, [], {})
    assert len(blocks) == 2
