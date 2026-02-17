"""
Step 15 — Missing Record Detection (Phase 3).

Deterministic coverage analysis that detects gaps in medical records based on the EvidenceGraph.
This implementation is purely graph-derived and does not use NLP or external APIs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Set

from packages.shared.models import ArtifactRef, EvidenceGraph
from packages.shared.storage import save_artifact


def detect_missing_records(
    evidence_graph: EvidenceGraph,
    providers_normalized: list[dict], # Provided for context, but we prioritize graph data
) -> dict:
    """
    Run missing-record detection based strictly on EvidenceGraph events.
    """
    # STEP 1 — Build deterministic visit date maps from EVENTS
    provider_visit_dates: dict[str, Set[date]] = {}
    global_visit_dates: Set[date] = set()

    # Mapping for provider display names
    provider_names: dict[str, str] = {
        p.provider_id: p.detected_name_raw for p in evidence_graph.providers
    }

    # Authoritative source of visit timing
    for event in evidence_graph.events:
        if not event.date:
            continue
        
        visit_date = event.date.sort_date()
        # Skip unknown/placeholder dates (sort_date returns 1900-01-01 for unknown)
        if visit_date.year <= 1900:
            continue

        global_visit_dates.add(visit_date)
        
        pid = event.provider_id
        if pid and pid != "unknown":
            if pid not in provider_visit_dates:
                provider_visit_dates[pid] = set()
            provider_visit_dates[pid].add(visit_date)

    # Pre-sort events by sort_key for "latest/earliest" logic
    sorted_events_for_evidence = sorted(
        evidence_graph.events, 
        key=lambda e: e.date.sort_key() if e.date else (99, "UNKNOWN")
    )

    # Sort dates ascending
    sorted_global_dates = sorted(list(global_visit_dates))
    
    sorted_provider_dates: dict[str, list[date]] = {}
    for pid, dates in provider_visit_dates.items():
        sorted_provider_dates[pid] = sorted(list(dates))

    gaps = []

    # STEP 2 — Compute PROVIDER GAPS
    for pid, visit_dates in sorted_provider_dates.items():
        if len(visit_dates) < 2:
            continue
        
        display_name = provider_names.get(pid, "Unknown Provider")

        for i in range(len(visit_dates) - 1):
            d1 = visit_dates[i]
            d2 = visit_dates[i+1]
            gap_days = (d2 - d1).days

            if gap_days >= 30:
                severity = "high" if gap_days >= 60 else "medium"
                
                # Stable hash for gap_id
                gap_seed = f"{pid}{d1.isoformat()}{d2.isoformat()}provider_gap_v1"
                gap_id = hashlib.sha256(gap_seed.encode()).hexdigest()[:16]

                # Find boundary events for evidence
                # We need all events on these dates for this provider to get citations
                events_on_d1 = [e for e in sorted_events_for_evidence 
                                if e.provider_id == pid and e.date and e.date.sort_date() == d1]
                events_on_d2 = [e for e in sorted_events_for_evidence 
                                if e.provider_id == pid and e.date and e.date.sort_date() == d2]
                
                # latest event on start_date
                last_event = events_on_d1[-1] if events_on_d1 else None
                # earliest event on end_date
                next_event = events_on_d2[0] if events_on_d2 else None

                citation_ids = set()
                if last_event:
                    citation_ids.update(last_event.citation_ids)
                if next_event:
                    citation_ids.update(next_event.citation_ids)

                gaps.append({
                    "gap_id": gap_id,
                    "provider_id": pid,
                    "provider_display_name": display_name,
                    "start_date": d1.isoformat(),
                    "end_date": d2.isoformat(),
                    "gap_days": gap_days,
                    "severity": severity,
                    "rule_name": "provider_gap",
                    "rationale": "No documented visits for provider during this period",
                    "evidence": {
                        "last_event_id": last_event.event_id if last_event else None,
                        "next_event_id": next_event.event_id if next_event else None,
                        "citation_ids": sorted(list(citation_ids))
                    },
                    "suggested_records_to_request": {
                        "provider_id": pid,
                        "from": (d1 + timedelta(days=1)).isoformat(),
                        "to": (d2 - timedelta(days=1)).isoformat(),
                        "type": "Medical records"
                    }
                })

    # STEP 3 — Compute GLOBAL GAPS
    for i in range(len(sorted_global_dates) - 1):
        d1 = sorted_global_dates[i]
        d2 = sorted_global_dates[i+1]
        gap_days = (d2 - d1).days

        if gap_days >= 45:
            severity = "high" if gap_days >= 90 else "medium"
            
            # Stable hash for gap_id
            gap_seed = f"{d1.isoformat()}{d2.isoformat()}global_gap_v1"
            gap_id = hashlib.sha256(gap_seed.encode()).hexdigest()[:16]

            # Find nearest events globally
            events_on_d1 = [e for e in sorted_events_for_evidence 
                            if e.date and e.date.sort_date() == d1]
            events_on_d2 = [e for e in sorted_events_for_evidence 
                            if e.date and e.date.sort_date() == d2]
            
            last_event = events_on_d1[-1] if events_on_d1 else None
            next_event = events_on_d2[0] if events_on_d2 else None

            citation_ids = set()
            if last_event:
                citation_ids.update(last_event.citation_ids)
            if next_event:
                citation_ids.update(next_event.citation_ids)

            gaps.append({
                "gap_id": gap_id,
                "provider_id": None,
                "provider_display_name": None,
                "start_date": d1.isoformat(),
                "end_date": d2.isoformat(),
                "gap_days": gap_days,
                "severity": severity,
                "rule_name": "global_gap",
                "rationale": "No documented medical activity during this period",
                "evidence": {
                    "last_event_id": last_event.event_id if last_event else None,
                    "next_event_id": next_event.event_id if next_event else None,
                    "citation_ids": sorted(list(citation_ids))
                },
                "suggested_records_to_request": {
                    "provider_id": None,
                    "from": (d1 + timedelta(days=1)).isoformat(),
                    "to": (d2 - timedelta(days=1)).isoformat(),
                    "type": "Any medical provider records"
                }
            })

    # Sort gaps by start_date then severity
    gaps.sort(key=lambda x: (x["start_date"], x["severity"] == "medium"))

    # STEP 4 — Store results in EvidenceGraph.extensions
    summary = {
        "total_gaps": len(gaps),
        "provider_gap_count": sum(1 for g in gaps if g["rule_name"] == "provider_gap"),
        "global_gap_count": sum(1 for g in gaps if g["rule_name"] == "global_gap"),
        "high_severity_count": sum(1 for g in gaps if g["severity"] == "high"),
        "medium_severity_count": sum(1 for g in gaps if g["severity"] == "medium"),
    }

    return {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ruleset": {
            "provider_gap_medium_days": 30,
            "provider_gap_high_days": 60,
            "global_gap_medium_days": 45,
            "global_gap_high_days": 90
        },
        "gaps": gaps,
        "summary": summary
    }


def render_missing_records(
    run_id: str,
    payload: dict,
) -> tuple[Optional[ArtifactRef], Optional[ArtifactRef]]:
    """Save missing_records artifacts and return refs."""
    import csv
    import io

    gaps = payload.get("gaps", [])

    # CSV Generation
    csv_buf = io.StringIO()
    csv_cols = [
        "gap_id", "rule_name", "severity", "provider_display_name", 
        "start_date", "end_date", "gap_days", "rationale"
    ]
    writer = csv.DictWriter(csv_buf, fieldnames=csv_cols, extrasaction="ignore")
    writer.writeheader()
    for gap in gaps:
        writer.writerow(gap)
    
    csv_bytes = csv_buf.getvalue().encode("utf-8")
    csv_path = save_artifact(run_id, "missing_records.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    csv_ref = ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes))

    # JSON Generation
    json_bytes = json.dumps(payload, indent=2, default=str).encode("utf-8")
    json_path = save_artifact(run_id, "missing_records.json", json_bytes)
    json_sha = hashlib.sha256(json_bytes).hexdigest()
    json_ref = ArtifactRef(uri=str(json_path), sha256=json_sha, bytes=len(json_bytes))

    return csv_ref, json_ref
