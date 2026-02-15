from __future__ import annotations
import hashlib
import re
import uuid
from packages.shared.models import (
    BBox,
    Citation,
    Fact,
    FactKind,
    Page,
)

def _make_citation(page: Page, snippet: str) -> Citation:
    """Create a citation for a fact extracted from a page."""
    text_hash = hashlib.sha256(snippet.encode()).hexdigest()
    return Citation(
        citation_id=uuid.uuid4().hex[:16],
        source_document_id=page.source_document_id,
        page_number=page.page_number,
        snippet=snippet[:500],
        bbox=BBox(x=0, y=0, w=0, h=0),  # bbox fallback — whole page
        text_hash=text_hash,
    )

def _make_fact(text: str, kind: FactKind, citation_id: str, verbatim: bool = False) -> Fact:
    return Fact(
        text=text[:400],
        kind=kind,
        verbatim=verbatim,
        citation_id=citation_id,
    )

def _find_section(text: str, header: str) -> str | None:
    """Find text after a section header, up to the next header or end."""
    pattern = rf"(?i){re.escape(header)}\s*:?\s*(.*?)(?=\n[A-Z][a-z]+\s*:|$)"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        content = m.group(1).strip()
        return content if len(content) > 5 else None
    return None
