from packages.shared.models import BBox, Citation, Page, PageType
from apps.worker.lib.provider_resolution_v1 import build_page_identity_map, resolve_page_identity, choose_best


def _page(page_no: int, text: str, page_type: PageType = PageType.PT_NOTE, doc: str = 'doc-1') -> Page:
    return Page(page_id=f'p-{page_no}', source_document_id=doc, page_number=page_no, text=text, text_source='ocr', page_type=page_type)


def _cit(page_no: int, cid: str) -> Citation:
    return Citation(citation_id=cid, source_document_id='doc-1', page_number=page_no, snippet='snippet', bbox=BBox(x=1, y=1, w=1, h=1))


def test_extracts_facility_from_pt_letterhead_page() -> None:
    p = _page(10, 'ELITE PHYSICAL THERAPY CENTER\n123 Main Street Suite 100\nSpringfield, CA 90210\nPhone: (555) 123-4567\nPT Daily Note\nDate: 11/19/2024')
    best = choose_best(resolve_page_identity(p, citations=[_cit(10, 'c10')]))
    assert best is not None
    assert 'elite physical therapy' in str(best.get('facility_name') or '').lower()
    assert float(best.get('confidence') or 0) >= 0.6
    assert best.get('resolved_from') in {'document_header', 'page_header'}


def test_propagates_document_identity_to_page_without_header() -> None:
    pages = [
        _page(20, 'ELITE PHYSICAL THERAPY\n456 Rehab Blvd\nSpringfield, CA 90210\nPhone: (555) 111-2222\nPT Daily Note', doc='doc-x'),
        _page(21, 'Subjective: neck pain\nObjective: ROM limited\nAssessment: improving\nPlan: continue therapy', doc='doc-x'),
    ]
    cits = [_cit(20, 'c20'), _cit(21, 'c21')]
    idmap = build_page_identity_map(pages=pages, citations=cits)
    row = idmap[21]
    assert row.get('resolved_from') == 'inferred'
    assert 'elite physical therapy' in str(row.get('facility_name') or '').lower()
    assert float(row.get('confidence') or 0) >= 0.6


def test_fax_from_phone_parsed_but_not_overconfident() -> None:
    p = _page(30, 'Fax ID: 12345\nFROM: (555) 222-3333\nPage 1\nPT Progress Summary')
    best = choose_best(resolve_page_identity(p, citations=[_cit(30, 'c30')]))
    assert best is not None
    assert best.get('resolved_from') == 'fax_metadata'
    assert float(best.get('confidence') or 0) < 0.6
    assert best.get('phone') == '(555) 222-3333'
