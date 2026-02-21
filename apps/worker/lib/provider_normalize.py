"""
Provider normalization utilities (Phase 1).

Enhanced provider entity normalization:
- Credential suffix stripping (MD, DO, PA-C, RN, PT, DC, etc.)
- Deterministic deduplication via stable normalization
- First/last seen date computation from linked events
- Coverage span computation per provider
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from packages.shared.models import (
    EvidenceGraph,
    EventDate,
    Provider,
)


# Credential suffixes to strip during normalization (order: longest first)
_CREDENTIAL_SUFFIXES = re.compile(
    r"""\b(
        pa-c | arnp | crna | aprn | lcsw | lmft |   # mid-levels
        md | do | dpm | dc | dds | dmd | od | phd |  # doctorates
        rn | lpn | lvn | cna |                        # nursing
        pt | dpt | ot | otr |                          # therapy
        np | fnp |                                      # nurse practitioners
        ms | ma | bs | ba |                            # degrees
        llc | inc | corp | pllc | pa | pc |            # business suffixes
        medical\s+group | associates | and\s+associates
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)


def normalize_provider_name(raw: str) -> str:
    """
    Enhanced provider name normalization.
    Deterministic: same input always produces same output.
    """
    name = raw.strip()
    # Casefold
    name = name.lower()
    # Strip credential suffixes
    name = _CREDENTIAL_SUFFIXES.sub("", name)
    # Remove punctuation (keep alphanumeric + whitespace)
    name = re.sub(r"[^\w\s]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    # Standardize common variants
    name = name.replace("saint", "st").replace("center", "ctr")
    return name


def normalize_provider_entities(
    evidence_graph: EvidenceGraph,
) -> list[dict]:
    """
    Produce normalized provider entities from the evidence graph.
    
    Merges providers with the same normalized name, computes:
    - display_name (best human-readable variant)
    - provider_type
    - first_seen_date / last_seen_date (from linked events)
    - event_count, citation_count
    
    Returns list of dicts suitable for extensions.providers_normalized.
    """
    # Build provider_id → Provider lookup
    provider_map = {p.provider_id: p for p in evidence_graph.providers}
    
    # Build provider_id → list of event dates
    provider_events: dict[str, list[Optional[date]]] = {}
    provider_event_counts: dict[str, int] = {}
    for evt in evidence_graph.events:
        pid = evt.provider_id
        if pid not in provider_events:
            provider_events[pid] = []
            provider_event_counts[pid] = 0
        provider_event_counts[pid] += 1
        if evt.date:
            try:
                provider_events[pid].append(evt.date.sort_date())
            except Exception:
                pass
    
    # Build provider_id → citation count
    provider_citation_counts: dict[str, int] = {}
    for evt in evidence_graph.events:
        pid = evt.provider_id
        if pid not in provider_citation_counts:
            provider_citation_counts[pid] = 0
        provider_citation_counts[pid] += len(evt.citation_ids)
    
    # Normalize and merge
    merged: dict[str, dict] = {}  # normalized_name → entity dict
    
    for provider in evidence_graph.providers:
        norm = normalize_provider_name(provider.detected_name_raw)
        if not norm:
            norm = normalize_provider_name(provider.normalized_name)
        if not norm:
            continue
        
        pid = provider.provider_id
        event_dates = [d for d in provider_events.get(pid, []) if d is not None]
        evt_count = provider_event_counts.get(pid, 0)
        cit_count = provider_citation_counts.get(pid, 0)
        
        if norm in merged:
            # Merge into existing entity
            entity = merged[norm]
            entity["event_count"] += evt_count
            entity["citation_count"] += cit_count
            entity["source_provider_ids"].append(pid)
            
            # Update date range
            for d in event_dates:
                if entity["first_seen_date"] is None or d < entity["first_seen_date"]:
                    entity["first_seen_date"] = d
                if entity["last_seen_date"] is None or d > entity["last_seen_date"]:
                    entity["last_seen_date"] = d
            
            # Keep best display name (prefer longer, more descriptive)
            if len(provider.detected_name_raw) > len(entity["display_name"]):
                entity["display_name"] = provider.detected_name_raw
        else:
            # New entity
            first_seen = min(event_dates) if event_dates else None
            last_seen = max(event_dates) if event_dates else None
            
            merged[norm] = {
                "normalized_name": norm,
                "display_name": provider.detected_name_raw,
                "provider_type": provider.provider_type.value,
                "first_seen_date": first_seen,
                "last_seen_date": last_seen,
                "event_count": evt_count,
                "citation_count": cit_count,
                "source_provider_ids": [pid],
            }
    
    # Sort by first_seen_date (nulls last), then by name
    entities = sorted(
        merged.values(),
        key=lambda e: (
            e["first_seen_date"] or date.max,
            e["normalized_name"],
        ),
    )
    
    # Serialize dates to ISO strings for JSON compatibility
    for entity in entities:
        if entity["first_seen_date"]:
            entity["first_seen_date"] = entity["first_seen_date"].isoformat()
        if entity["last_seen_date"]:
            entity["last_seen_date"] = entity["last_seen_date"].isoformat()
    
    return entities


def compute_coverage_spans(
    providers_normalized: list[dict],
) -> list[dict]:
    """
    Compute coverage spans per normalized provider entity.
    
    A coverage span is the observed date range for a provider:
    [first_seen_date, last_seen_date].
    
    Returns list of dicts for extensions.coverage_spans.
    """
    spans = []
    for entity in providers_normalized:
        if entity.get("first_seen_date") and entity.get("last_seen_date"):
            spans.append({
                "provider_name": entity["display_name"],
                "normalized_name": entity["normalized_name"],
                "provider_type": entity["provider_type"],
                "start_date": entity["first_seen_date"],
                "end_date": entity["last_seen_date"],
                "event_count": entity["event_count"],
            })
    return spans
