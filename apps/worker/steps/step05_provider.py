"""
Step 5 — Provider detection + normalization.
Detect provider names from letterhead and labels, normalize, and fuzzy-cluster.
"""
from __future__ import annotations

import re
import uuid

from packages.shared.models import (
    BBox,
    Document,
    Page,
    Provider,
    ProviderEvidence,
    ProviderType,
    Warning,
)

_PROVIDER_LABEL_PATTERNS = [
    r"(?:facility|provider|rendering provider|attending|clinic|hospital|radiology)\s*:\s*(.+)",
    r"(?:physician|doctor|md|do)\s*:\s*(.+)",
]

_SUFFIX_STRIP = re.compile(
    r"\b(llc|inc|corp|medical group|pa|pc|pllc|md|do|dpm|dc|pt|dds)\b",
    re.IGNORECASE,
)

_PROVIDER_TYPE_KEYWORDS: dict[ProviderType, list[str]] = {
    ProviderType.ER: ["emergency", "er ", "ed ", "emergency department"],
    ProviderType.PT: ["physical therapy", "rehabilitation", "pt "],
    ProviderType.IMAGING: ["radiology", "imaging", "mri", "ct scan"],
    ProviderType.HOSPITAL: ["hospital", "medical center"],
    ProviderType.PCP: ["family medicine", "primary care", "internal medicine"],
    ProviderType.SPECIALIST: ["orthopedic", "neurology", "cardiology", "surgery"],
}


def _normalize_name(raw: str) -> str:
    """Normalize a provider name for clustering."""
    name = raw.strip().lower()
    name = _SUFFIX_STRIP.sub("", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Standardize common variants
    name = name.replace("saint", "st").replace("center", "ctr")
    return name


def _detect_provider_type(text: str) -> ProviderType:
    """Detect provider type from surrounding text."""
    text_lower = text.lower()
    for ptype, keywords in _PROVIDER_TYPE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return ptype
    return ProviderType.UNKNOWN


def _extract_candidates_from_page(page: Page) -> list[tuple[str, int]]:
    """
    Extract provider name candidates from a page.
    Returns list of (raw_name, confidence).
    """
    candidates: list[tuple[str, int]] = []
    lines = page.text.split("\n")

    # Check labels first (higher confidence)
    for line in lines:
        for pattern in _PROVIDER_LABEL_PATTERNS:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if len(name) >= 3 and len(name) <= 200:
                    candidates.append((name, 80))

    # Check letterhead (top 20% of page text = first few lines)
    top_lines = lines[:max(3, len(lines) // 5)]
    for line in top_lines:
        line_stripped = line.strip()
        # Letterhead heuristic: short-ish lines with title-case, no obvious sentence structure
        if (10 <= len(line_stripped) <= 120
                and not line_stripped.endswith(".")
                and re.search(r"[A-Z]", line_stripped)):
            # Looks like it could be a facility/provider name
            if any(kw in line_stripped.lower() for kw in
                   ["medical", "hospital", "clinic", "health", "center", "radiology",
                    "therapy", "orthopedic", "chiropractic", "imaging"]):
                candidates.append((line_stripped, 70))

    return candidates


def _simple_fuzzy_match(a: str, b: str) -> float:
    """Simple token-set similarity for provider name clustering."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


def detect_providers(
    pages: list[Page],
    documents: list[Document],
) -> tuple[list[Provider], dict[int, str], list[Warning]]:
    """
    Detect and normalize providers across all pages.
    Returns (providers, page_provider_map, warnings).
    """
    warnings: list[Warning] = []
    raw_candidates: list[tuple[str, int, int]] = []  # (raw_name, confidence, page_number)

    for page in pages:
        for raw_name, conf in _extract_candidates_from_page(page):
            raw_candidates.append((raw_name, conf, page.page_number))

    if not raw_candidates:
        # Create a default "Unknown Provider"
        default = Provider(
            provider_id=uuid.uuid4().hex[:16],
            detected_name_raw="Unknown Provider",
            normalized_name="unknown provider",
            provider_type=ProviderType.UNKNOWN,
            confidence=0,
        )
        warnings.append(Warning(
            code="NO_PROVIDERS_DETECTED",
            message="No provider names could be detected from any page",
        ))
        return [default], {}, warnings

    # Cluster by normalized name with fuzzy matching
    providers: list[Provider] = []
    seen_normalized: dict[str, Provider] = {}

    for raw_name, conf, page_num in raw_candidates:
        normalized = _normalize_name(raw_name)
        if not normalized:
            continue

        # Check if matches an existing cluster
        matched_key = None
        for key in seen_normalized:
            if _simple_fuzzy_match(normalized, key) >= 0.6:
                matched_key = key
                break

        if matched_key:
            prov = seen_normalized[matched_key]
            prov.evidence.append(ProviderEvidence(
                page_number=page_num,
                snippet=raw_name[:260],
                bbox=BBox(x=0, y=0, w=0, h=0),
            ))
            prov.confidence = max(prov.confidence, conf)
        else:
            page_text = next((p.text for p in pages if p.page_number == page_num), "")
            prov = Provider(
                provider_id=uuid.uuid4().hex[:16],
                detected_name_raw=raw_name[:200],
                normalized_name=normalized[:200],
                provider_type=_detect_provider_type(page_text),
                confidence=conf,
                evidence=[ProviderEvidence(
                    page_number=page_num,
                    snippet=raw_name[:260],
                    bbox=BBox(x=0, y=0, w=0, h=0),
                )],
            )
            seen_normalized[normalized] = prov
            providers.append(prov)

    # Build page_provider_map (best provider per page)
    page_provider_map: dict[int, str] = {}
    
    # First, map normalized names to the final provider objects
    norm_to_provider = {p.normalized_name: p for p in providers}
    
    # Group candidates by page
    page_candidates: dict[int, list[tuple[str, int]]] = {}
    for raw, conf, pnum in raw_candidates:
        if pnum not in page_candidates:
            page_candidates[pnum] = []
        page_candidates[pnum].append((raw, conf))
        
    for pnum, cands in page_candidates.items():
        # Find best candidate on this page
        best_cand = max(cands, key=lambda x: x[1]) # max by confidence
        raw_name = best_cand[0]
        norm = _normalize_name(raw_name)
        
        # Find which provider cluster this belongs to
        # (Re-use the same fuzzy logic or just direct lookup if we can)
        # Since we already clustered everyone in `providers`, we can try to find the match.
        
        # Optimization: fast lookup first
        if norm in norm_to_provider:
            page_provider_map[pnum] = norm_to_provider[norm].provider_id
            continue
            
        # Fallback fuzzy lookup (same as above loop)
        for key, prov in seen_normalized.items():
             if _simple_fuzzy_match(norm, key) >= 0.6:
                 page_provider_map[pnum] = prov.provider_id
                 break

    return providers, page_provider_map, warnings
