"""
Step 8 — Citation capture (snippet + bbox).
Ensure every extracted Fact has a proper citation with text_hash.
This step is largely handled inline by step07, but this module
provides post-processing: hash validation and bbox fallback warnings.
"""
from __future__ import annotations

import hashlib

from packages.shared.models import BBox, Citation, Warning


def post_process_citations(citations: list[Citation]) -> tuple[list[Citation], list[Warning]]:
    """
    Post-process citations:
    - Ensure text_hash is set
    - Warn on bbox fallback (all zeros)
    """
    warnings: list[Warning] = []

    for cit in citations:
        # Ensure text_hash
        if not cit.text_hash:
            cit.text_hash = hashlib.sha256(cit.snippet.encode()).hexdigest()

        # Check bbox fallback
        if cit.bbox.x == 0 and cit.bbox.y == 0 and cit.bbox.w == 0 and cit.bbox.h == 0:
            warnings.append(Warning(
                code="BBOX_FALLBACK",
                message=f"Citation {cit.citation_id} on page {cit.page_number} uses whole-page bbox fallback",
                page=cit.page_number,
                document_id=cit.source_document_id,
            ))

    return citations, warnings
