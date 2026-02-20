"""
Helper functions for export orchestration.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import TYPE_CHECKING

from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.export_render.common import parse_date_string

if TYPE_CHECKING:
    pass


def _normalize_projection_patient_labels(projection: ChronologyProjection) -> ChronologyProjection:
    labels = {e.patient_label for e in projection.entries if e.patient_label != "Unknown Patient"}
    if len(labels) == 1:
        canonical = list(labels)[0]
        new_entries = [e.model_copy(update={"patient_label": canonical}) for e in projection.entries]
        return projection.model_copy(update={"entries": new_entries})
    return projection


def _merge_projection_entries_same_day(projection: ChronologyProjection) -> ChronologyProjection:
    if not projection.entries:
        return projection
    
    merged: list[ChronologyProjectionEntry] = []
    # Group by (date, provider, patient, type)
    groups: dict[tuple, list[ChronologyProjectionEntry]] = {}
    for entry in projection.entries:
        key = (entry.date_display, entry.provider_display, entry.patient_label, entry.event_type_display)
        if key not in groups:
            groups[key] = []
        groups[key].append(entry)
    
    # We want to preserve original order as much as possible, but regrouped.
    # To keep it simple and deterministic, we'll just iterate in order of appearance.
    seen_keys = []
    key_to_entries = {}
    for entry in projection.entries:
        key = (entry.date_display, entry.provider_display, entry.patient_label, entry.event_type_display)
        if key not in key_to_entries:
            seen_keys.append(key)
            key_to_entries[key] = []
        key_to_entries[key].append(entry)

    for key in seen_keys:
        ents = key_to_entries[key]
        if len(ents) == 1:
            merged.append(ents[0])
            continue
        
        # Merge facts and citations
        all_facts = []
        all_citations = []
        for e in ents:
            all_facts.extend(e.facts or [])
            if e.citation_display:
                all_citations.append(e.citation_display)
        
        # Dedupe facts while preserving order
        unique_facts = []
        fact_seen = set()
        for f in all_facts:
            f_low = f.strip().lower()
            if f_low and f_low not in fact_seen:
                unique_facts.append(f)
                fact_seen.add(f_low)
        
        # Dedupe citations
        unique_cites = ", ".join(dict.fromkeys([c.strip() for c in (", ".join(all_citations)).split(",") if c.strip()]))
        
        merged.append(ents[0].model_copy(update={
            "facts": unique_facts,
            "citation_display": unique_cites,
            "event_id": f"merged_{hashlib.sha1(str(key).encode('utf-8')).hexdigest()[:8]}_{ents[0].event_id}"
        }))
        
    return projection.model_copy(update={"entries": merged})


def _compute_care_window_from_projection(projection: ChronologyProjection) -> tuple[date, date] | None:
    dates = []
    for entry in projection.entries:
        d = parse_date_string(entry.date_display)
        if d:
            dates.append(d)
    if not dates:
        return None
    return min(dates), max(dates)
