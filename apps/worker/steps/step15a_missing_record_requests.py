"""
Step 15a - Missing Record Request Generator (Phase 4).

Pure deterministic transformation of missing_records gaps into
paralegal-ready provider request artifacts.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from packages.shared.models import (
    ArtifactRef,
    EvidenceGraph,
    MissingRecordRequestsExtension,
    MissingRecordsExtension,
)
from packages.shared.storage import save_artifact

_CSV_COLUMNS = [
    "request_id",
    "provider_display_name",
    "provider_id",
    "from_date",
    "to_date",
    "priority",
    "gap_days",
    "severity",
]


def _priority_for_severity(severity: str) -> str:
    if severity == "high":
        return "urgent"
    return "standard"


def _title_case_priority(priority: str) -> str:
    return "Urgent" if priority == "urgent" else "Standard"


def _request_id(provider_id: str, from_date: str, to_date: str) -> str:
    seed = f"{provider_id}{from_date}{to_date}request_v1"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _merge_provider_gaps(provider_gaps: list[dict]) -> list[dict]:
    """
    Merge overlapping or adjacent date ranges (<= 1 day between ranges)
    for a single provider. Input must be pre-sorted deterministically.
    """
    if not provider_gaps:
        return []

    merged: list[dict] = []
    current = None

    for gap in provider_gaps:
        start = date.fromisoformat(gap["start_date"])
        end = date.fromisoformat(gap["end_date"])

        if current is None:
            current = {
                "provider_id": gap["provider_id"],
                "provider_display_name": gap.get("provider_display_name") or "Unknown Provider",
                "start_date": start,
                "end_date": end,
                "source_gaps": [gap],
            }
            continue

        if start <= (current["end_date"] + timedelta(days=1)):
            if end > current["end_date"]:
                current["end_date"] = end
            current["source_gaps"].append(gap)
        else:
            merged.append(current)
            current = {
                "provider_id": gap["provider_id"],
                "provider_display_name": gap.get("provider_display_name") or "Unknown Provider",
                "start_date": start,
                "end_date": end,
                "source_gaps": [gap],
            }

    if current is not None:
        merged.append(current)

    return merged


def generate_missing_record_requests(evidence_graph: EvidenceGraph) -> dict:
    """
    Generate missing record requests from EvidenceGraph.extensions.missing_records.gaps.
    """
    missing_records_raw = evidence_graph.extensions.get("missing_records", {})
    if missing_records_raw:
        missing_records = MissingRecordsExtension.model_validate(missing_records_raw).model_dump(mode="json")
    else:
        missing_records = {"gaps": []}
    gaps = missing_records.get("gaps", [])

    provider_gaps = [
        g for g in gaps
        if g.get("provider_id")
        and g.get("start_date")
        and g.get("end_date")
        and g.get("severity") in {"high", "medium"}
    ]

    provider_gaps.sort(
        key=lambda g: (
            g.get("provider_id", ""),
            g.get("start_date", ""),
            g.get("end_date", ""),
            g.get("gap_id", ""),
        )
    )

    by_provider: dict[str, list[dict]] = {}
    for gap in provider_gaps:
        pid = gap["provider_id"]
        by_provider.setdefault(pid, []).append(gap)

    requests: list[dict] = []
    for pid in sorted(by_provider.keys()):
        merged_ranges = _merge_provider_gaps(by_provider[pid])
        for merged in merged_ranges:
            source_gaps = merged["source_gaps"]
            source_gaps_sorted = sorted(
                source_gaps,
                key=lambda g: (
                    g.get("start_date", ""),
                    g.get("end_date", ""),
                    g.get("gap_id", ""),
                ),
            )
            primary_gap = source_gaps_sorted[0]
            merged_severity = "high" if any(g.get("severity") == "high" for g in source_gaps_sorted) else "medium"
            priority = _priority_for_severity(merged_severity)

            from_date = merged["start_date"].isoformat()
            to_date = merged["end_date"].isoformat()

            requests.append({
                "request_id": _request_id(pid, from_date, to_date),
                "provider_id": pid,
                "provider_display_name": merged["provider_display_name"],
                "request_date_range": {
                    "from_date": from_date,
                    "to_date": to_date,
                },
                "gap_reference": {
                    "gap_id": primary_gap.get("gap_id"),
                    "gap_days": primary_gap.get("gap_days"),
                    "severity": merged_severity,
                },
                "request_priority": priority,
                "request_type": "medical_records",
                "request_rationale": (
                    f"Missing records detected between {from_date} and {to_date} "
                    "based on chronology gap analysis."
                ),
                "merged_gap_ids": [g.get("gap_id") for g in source_gaps_sorted if g.get("gap_id")],
            })

    priority_order = {"urgent": 0, "standard": 1}
    requests.sort(
        key=lambda r: (
            priority_order.get(r["request_priority"], 99),
            r.get("provider_display_name", ""),
            r.get("request_date_range", {}).get("from_date", ""),
            r.get("request_id", ""),
        )
    )

    payload = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requests": requests,
    }
    return MissingRecordRequestsExtension.model_validate(payload).model_dump(mode="json")


def generate_missing_record_requests_csv(payload: dict) -> bytes:
    requests = payload.get("requests", [])
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    writer.writeheader()

    for req in requests:
        writer.writerow({
            "request_id": req.get("request_id"),
            "provider_display_name": req.get("provider_display_name"),
            "provider_id": req.get("provider_id"),
            "from_date": req.get("request_date_range", {}).get("from_date"),
            "to_date": req.get("request_date_range", {}).get("to_date"),
            "priority": req.get("request_priority"),
            "gap_days": req.get("gap_reference", {}).get("gap_days"),
            "severity": req.get("gap_reference", {}).get("severity"),
        })

    return buf.getvalue().encode("utf-8")


def generate_missing_record_requests_json(payload: dict) -> bytes:
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def generate_missing_record_requests_md(payload: dict) -> bytes:
    requests = payload.get("requests", [])
    lines = ["# Missing Record Requests", ""]

    for req in requests:
        provider_name = req.get("provider_display_name") or "Unknown Provider"
        from_date = req.get("request_date_range", {}).get("from_date", "")
        to_date = req.get("request_date_range", {}).get("to_date", "")
        priority = _title_case_priority(req.get("request_priority", "standard"))

        lines.append(f"## Provider: {provider_name}")
        lines.append("")
        lines.append("Request records from:")
        lines.append(f"{from_date} to {to_date}")
        lines.append("")
        lines.append(f"Priority: {priority}")
        lines.append("Reason: Chronology gap detected")
        lines.append("")

    return "\n".join(lines).encode("utf-8")


def render_missing_record_requests(
    run_id: str,
    payload: dict,
) -> tuple[Optional[ArtifactRef], Optional[ArtifactRef], Optional[ArtifactRef]]:
    """Save missing_record_requests artifacts and return refs (csv, json, md)."""
    csv_bytes = generate_missing_record_requests_csv(payload)
    csv_path = save_artifact(run_id, "missing_record_requests.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    csv_ref = ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes))

    json_bytes = generate_missing_record_requests_json(payload)
    json_path = save_artifact(run_id, "missing_record_requests.json", json_bytes)
    json_sha = hashlib.sha256(json_bytes).hexdigest()
    json_ref = ArtifactRef(uri=str(json_path), sha256=json_sha, bytes=len(json_bytes))

    md_bytes = generate_missing_record_requests_md(payload)
    md_path = save_artifact(run_id, "missing_record_requests.md", md_bytes)
    md_sha = hashlib.sha256(md_bytes).hexdigest()
    md_ref = ArtifactRef(uri=str(md_path), sha256=md_sha, bytes=len(md_bytes))

    return csv_ref, json_ref, md_ref
