"""
Step 15 — Missing Record Detection (Phase 3).

Deterministic coverage analysis that detects:
A) Global timeline gaps (> configurable threshold between any events)
B) Provider-specific gaps (within a provider's coverage span)
C) Continuity mention triggers (regex phrases implying missing records)

All findings are graph-derived. No external APIs or LLMs.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from packages.shared.models import ArtifactRef, EvidenceGraph
from packages.shared.storage import save_artifact


# ── Continuity trigger patterns ──────────────────────────────────────────

_CONTINUITY_PATTERNS: list[tuple[str, str, str]] = [
    # (pattern, implied_type, reason_code)
    (r"follow[\s-]*up\s+in\s+\d+", "visit", "FOLLOWUP_MENTION"),
    (r"return\s+in\s+\d+", "visit", "FOLLOWUP_MENTION"),
    (r"next\s+appointment", "visit", "FOLLOWUP_MENTION"),
    (r"continue\s+physical\s+therapy", "pt", "PT_COURSE_GAP"),
    (r"pt\s+\d+\s*x?\s*/?\s*(?:week|wk)", "pt", "PT_COURSE_GAP"),
    (r"referred\s+to", "visit", "REFERRAL_MENTION"),
    (r"refer\s+to", "visit", "REFERRAL_MENTION"),
    (r"ordered?\s+(?:an?\s+)?mri", "imaging", "IMAGING_ORDERED"),
    (r"ordered?\s+(?:an?\s+)?ct", "imaging", "IMAGING_ORDERED"),
    (r"ordered?\s+(?:an?\s+)?x[\s-]*ray", "imaging", "IMAGING_ORDERED"),
    (r"pending\s+imaging", "imaging", "IMAGING_ORDERED"),
    (r"ordered?\s+(?:lab|blood)", "labs", "LABS_ORDERED"),
    (r"pending\s+lab", "labs", "LABS_ORDERED"),
]

_COMPILED_TRIGGERS = [
    (re.compile(pat, re.IGNORECASE), imp_type, reason)
    for pat, imp_type, reason in _CONTINUITY_PATTERNS
]


# ── Gap detection helpers ────────────────────────────────────────────────

def _detect_global_gaps(
    evidence_graph: EvidenceGraph,
    threshold_days: int = 14,
) -> list[dict]:
    """
    Detect global timeline gaps between consecutive dated events.
    """
    # Collect events with resolved dates
    dated_events = []
    for evt in evidence_graph.events:
        if evt.date:
            try:
                d = evt.date.sort_date()
                dated_events.append((d, evt))
            except Exception:
                pass

    if len(dated_events) < 2:
        return []

    # Sort by date, then event_id for determinism
    dated_events.sort(key=lambda x: (x[0], x[1].event_id))

    findings = []
    for i in range(len(dated_events) - 1):
        prev_date, prev_evt = dated_events[i]
        next_date, next_evt = dated_events[i + 1]
        gap_days = (next_date - prev_date).days

        if gap_days > threshold_days:
            # Gather citation_ids from boundary events
            cit_ids = list(set(prev_evt.citation_ids + next_evt.citation_ids))
            page_nums = list(set(prev_evt.source_page_numbers + next_evt.source_page_numbers))

            findings.append({
                "id": uuid.uuid4().hex[:16],
                "finding_type": "global_gap",
                "provider_entity_id": None,
                "span_start": prev_date.isoformat(),
                "span_end": next_date.isoformat(),
                "gap_days": gap_days,
                "implied_record_type": None,
                "reason_code": "GAP_OVER_THRESHOLD",
                "confidence": min(0.9, 0.5 + (gap_days / 365)),
                "citation_ids": sorted(cit_ids),
                "source_page_numbers": sorted(page_nums),
                "notes": f"No events found between {prev_date} and {next_date} ({gap_days} days)",
                "prev_event_id": prev_evt.event_id,
                "next_event_id": next_evt.event_id,
            })

    return findings


def _detect_provider_gaps(
    evidence_graph: EvidenceGraph,
    providers_normalized: list[dict],
    pt_threshold_days: int = 7,
    default_threshold_days: int = 30,
) -> list[dict]:
    """
    Detect gaps within each provider's treatment timeline.
    """
    # Build provider_id → normalized_name mapping
    pid_to_norm: dict[str, str] = {}
    norm_to_entity: dict[str, dict] = {}
    for entity in providers_normalized:
        norm_to_entity[entity["normalized_name"]] = entity
        for pid in entity.get("source_provider_ids", []):
            pid_to_norm[pid] = entity["normalized_name"]

    # Group events by normalized provider, sorted by date
    provider_events: dict[str, list[tuple[date, object]]] = {}
    for evt in evidence_graph.events:
        if not evt.date:
            continue
        try:
            d = evt.date.sort_date()
        except Exception:
            continue
        norm = pid_to_norm.get(evt.provider_id)
        if not norm:
            continue
        if norm not in provider_events:
            provider_events[norm] = []
        provider_events[norm].append((d, evt))

    findings = []
    for norm_name, events in provider_events.items():
        if len(events) < 2:
            continue

        events.sort(key=lambda x: (x[0], x[1].event_id))
        entity = norm_to_entity.get(norm_name, {})
        ptype = entity.get("provider_type", "unknown")
        threshold = pt_threshold_days if ptype == "pt" else default_threshold_days

        for i in range(len(events) - 1):
            prev_date, prev_evt = events[i]
            next_date, next_evt = events[i + 1]
            gap_days = (next_date - prev_date).days

            if gap_days > threshold:
                cit_ids = list(set(prev_evt.citation_ids + next_evt.citation_ids))
                page_nums = list(set(prev_evt.source_page_numbers + next_evt.source_page_numbers))

                findings.append({
                    "id": uuid.uuid4().hex[:16],
                    "finding_type": "provider_gap",
                    "provider_entity_id": norm_name,
                    "span_start": prev_date.isoformat(),
                    "span_end": next_date.isoformat(),
                    "gap_days": gap_days,
                    "implied_record_type": None,
                    "reason_code": "PT_COURSE_GAP" if ptype == "pt" else "GAP_OVER_THRESHOLD",
                    "confidence": min(0.85, 0.4 + (gap_days / 180)),
                    "citation_ids": sorted(cit_ids),
                    "source_page_numbers": sorted(page_nums),
                    "notes": f"Provider '{entity.get('display_name', norm_name)}': "
                             f"no events between {prev_date} and {next_date} ({gap_days} days)",
                })

    return findings


def _detect_continuity_mentions(
    evidence_graph: EvidenceGraph,
) -> list[dict]:
    """
    Scan page text for phrases implying missing records.
    """
    findings = []
    seen_keys: set[str] = set()  # Deduplicate same trigger on same page

    for page in evidence_graph.pages:
        text = page.text or ""
        for compiled_re, implied_type, reason_code in _COMPILED_TRIGGERS:
            match = compiled_re.search(text)
            if match:
                snippet = text[max(0, match.start() - 30):match.end() + 30].strip()
                dedup_key = f"{page.page_number}:{reason_code}:{implied_type}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                # Find citation from this page if available
                page_cits = [
                    c.citation_id for c in evidence_graph.citations
                    if c.page_number == page.page_number
                ]

                findings.append({
                    "id": uuid.uuid4().hex[:16],
                    "finding_type": "continuity_mention",
                    "provider_entity_id": None,
                    "span_start": None,
                    "span_end": None,
                    "gap_days": None,
                    "implied_record_type": implied_type,
                    "reason_code": reason_code,
                    "confidence": 0.6,
                    "citation_ids": sorted(page_cits[:3]),  # Cap at 3 citations
                    "source_page_numbers": [page.page_number],
                    "notes": snippet[:200],
                })

    return findings


# ── Main step function ───────────────────────────────────────────────────

def detect_missing_records(
    evidence_graph: EvidenceGraph,
    providers_normalized: list[dict],
    global_gap_threshold: int = 14,
    pt_gap_threshold: int = 7,
    provider_gap_threshold: int = 30,
) -> dict:
    """
    Run all missing-record detectors and return the extensions payload.
    """
    global_gaps = _detect_global_gaps(evidence_graph, global_gap_threshold)
    provider_gaps = _detect_provider_gaps(
        evidence_graph, providers_normalized,
        pt_gap_threshold, provider_gap_threshold,
    )
    continuity = _detect_continuity_mentions(evidence_graph)

    all_findings = global_gaps + provider_gaps + continuity

    # Stable sort: type, date, provider, id
    all_findings.sort(key=lambda f: (
        f["finding_type"],
        f.get("span_start") or "",
        f.get("provider_entity_id") or "",
        f["id"],
    ))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params": {
            "global_gap_threshold_days": global_gap_threshold,
            "pt_gap_threshold_days": pt_gap_threshold,
            "provider_gap_threshold_days": provider_gap_threshold,
        },
        "findings": all_findings,
        "metrics": {
            "total_findings": len(all_findings),
            "global_gaps": len(global_gaps),
            "provider_gaps": len(provider_gaps),
            "continuity_mentions": len(continuity),
        },
    }


# ── Artifact rendering ───────────────────────────────────────────────────

_CSV_COLUMNS = [
    "id", "finding_type", "provider_entity_id", "span_start", "span_end",
    "gap_days", "implied_record_type", "reason_code", "confidence",
    "citation_ids", "source_page_numbers", "notes",
]


def generate_missing_records_csv(findings: list[dict]) -> bytes:
    """Generate CSV artifact."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for f in findings:
        row = dict(f)
        row["citation_ids"] = ";".join(row.get("citation_ids", []))
        row["source_page_numbers"] = ";".join(str(p) for p in row.get("source_page_numbers", []))
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def generate_missing_records_json(payload: dict) -> bytes:
    """Generate JSON artifact."""
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def render_missing_records(
    run_id: str,
    payload: dict,
) -> tuple[Optional[ArtifactRef], Optional[ArtifactRef]]:
    """Save missing_records artifacts and return refs."""
    findings = payload.get("findings", [])

    # CSV
    csv_bytes = generate_missing_records_csv(findings)
    csv_path = save_artifact(run_id, "missing_records.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    csv_ref = ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes))

    # JSON
    json_bytes = generate_missing_records_json(payload)
    json_path = save_artifact(run_id, "missing_records.json", json_bytes)
    json_sha = hashlib.sha256(json_bytes).hexdigest()
    json_ref = ArtifactRef(uri=str(json_path), sha256=json_sha, bytes=len(json_bytes))

    return csv_ref, json_ref
