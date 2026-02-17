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
        citation_ids=[citation_id] if citation_id else []
    )

def _find_section(text: str, header: str) -> str | None:
    """
    Find text after a section header, up to the next header or end.
    
    Multi-strategy parser:
      1. Exact header line match (handles UPPER, Title, numbered)
      2. Inline header match (header embedded in a line)
      3. Original regex fallback
    """
    if not text or not header:
        return None

    lines = text.split("\n")
    header_lower = header.lower().strip()

    # ── Strategy 1: Line-level header detection ───────────────────────
    # Look for lines that ARE the header (possibly with colon, dash, number prefix)
    header_line_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Normalize: remove leading numbers/bullets, trailing colons/dashes
        normalized = re.sub(r"^[\d\.\)\-\*•]+\s*", "", stripped)  # strip "1. ", "- ", "• "
        normalized = re.sub(r"\s*[:;\-–—]+\s*$", "", normalized)  # strip trailing : ; -
        if normalized.lower() == header_lower:
            header_line_idx = i
            break
        # Also try partial match at start (e.g. "Assessment and Plan" matches "Assessment")
        if normalized.lower().startswith(header_lower) and len(normalized) < len(header) + 20:
            header_line_idx = i
            break

    if header_line_idx is not None:
        # Collect content from next line until boundary
        content_lines = []
        for j in range(header_line_idx + 1, len(lines)):
            line = lines[j]
            stripped = line.strip()
            # Stop at next section header (capitalized word followed by colon, or ALL CAPS line)
            if stripped and _is_header_boundary(stripped):
                break
            content_lines.append(stripped)

        content = "\n".join(content_lines).strip()
        if len(content) > 5:
            return content[:2000]

    # ── Strategy 2: Inline header (header: content on same line) ──────
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match "Header: content" or "HEADER: content"
        pattern = rf"(?i)(?:^|\d+\.\s*){re.escape(header)}\s*[:;\-–—]\s*(.+)"
        m = re.search(pattern, stripped)
        if m:
            first_line_content = m.group(1).strip()
            # Also grab continuation lines
            content_lines = [first_line_content]
            for j in range(i + 1, len(lines)):
                next_line = lines[j].strip()
                if not next_line or _is_header_boundary(next_line):
                    break
                content_lines.append(next_line)
            content = "\n".join(content_lines).strip()
            if len(content) > 5:
                return content[:2000]

    # ── Strategy 3: Original regex fallback ───────────────────────────
    pattern = rf"(?i){re.escape(header)}\s*:?\s*(.*?)(?=\n[A-Z][a-z]+\s*:|$)"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        content = m.group(1).strip()
        return content[:2000] if len(content) > 5 else None

    return None


def _is_header_boundary(line: str) -> bool:
    """Check if a line looks like a section header boundary."""
    stripped = line.strip()
    if not stripped:
        return False
    # All-caps line with 3+ chars (e.g. "ASSESSMENT", "PLAN")
    if stripped.isupper() and len(stripped) >= 3 and stripped.replace(" ", "").isalpha():
        return True
    # Title case with colon (e.g. "Assessment:", "Plan:", "History of Present Illness:")
    if re.match(r"^[A-Z][a-zA-Z\s]{2,40}:\s*$", stripped):
        return True
    # Numbered header (e.g. "1. Assessment:", "2. Plan:")
    if re.match(r"^\d+\.\s+[A-Z]", stripped):
        return True
    # Dashed/underlined separator
    if re.match(r"^[-=_]{3,}$", stripped):
        return True
    return False
