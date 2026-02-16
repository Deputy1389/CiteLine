"""
Step 16 — Billing Lines extraction (Phase 4).

Extracts atomic billing lines from billing pages into
extensions.billing_lines. Each line has amount, type, codes,
dates, and citation references.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import date
from typing import Optional

from packages.shared.models import ArtifactRef, EvidenceGraph, PageType
from packages.shared.storage import save_artifact
from apps.worker.lib.billing_extract import (
    classify_amount_type,
    extract_billing_date,
    extract_codes,
    is_billing_text,
    parse_amounts,
)


def extract_billing_lines(
    evidence_graph: EvidenceGraph,
    providers_normalized: list[dict],
) -> dict:
    """
    Extract atomic billing lines from billing pages.
    Returns extensions payload for billing_lines.
    """
    # Build page_number → provider mapping from normalized providers
    page_to_provider: dict[int, str] = {}
    for entity in providers_normalized:
        for pid in entity.get("source_provider_ids", []):
            # Find events for this provider to get page numbers
            for evt in evidence_graph.events:
                if evt.provider_id == pid:
                    for pnum in evt.source_page_numbers:
                        if pnum not in page_to_provider:
                            page_to_provider[pnum] = entity.get("normalized_name", "")

    # Identify billing pages
    billing_pages = []
    for page in evidence_graph.pages:
        is_billing = (
            page.page_type in (PageType.BILLING, None)
            and is_billing_text(page.text or "")
        ) or page.page_type == PageType.BILLING
        if is_billing:
            billing_pages.append(page)

    lines: list[dict] = []

    for page in billing_pages:
        text = page.text or ""
        text_lines = text.split("\n")

        # Get citations for this page
        page_cits = [
            c.citation_id for c in evidence_graph.citations
            if c.page_number == page.page_number
        ]

        for line_text in text_lines:
            amounts = parse_amounts(line_text)
            if not amounts:
                continue

            # Extract codes and date for this line
            codes = extract_codes(line_text)
            service_date = extract_billing_date(line_text)
            amount_type = classify_amount_type(line_text)

            # Try to get description (text before first $ or amount)
            description = line_text.strip()
            if len(description) > 200:
                description = description[:200]

            provider_norm = page_to_provider.get(page.page_number)
            flags = []
            if not provider_norm:
                flags.append("PROVIDER_UNRESOLVED")

            for amount_val, _, _ in amounts:
                # Normalize sign for payment bucket
                actual_amount = amount_val
                actual_type = amount_type
                if actual_amount < 0 and actual_type == "unknown":
                    actual_type = "payment"
                    actual_amount = abs(actual_amount)

                lines.append({
                    "id": uuid.uuid4().hex[:16],
                    "provider_entity_id": provider_norm,
                    "service_date": service_date.isoformat() if service_date else None,
                    "post_date": None,  # Not reliably extractable
                    "description": description,
                    "code": codes[0] if codes else None,
                    "units": None,
                    "amount": f"{actual_amount:.2f}",
                    "amount_type": actual_type,
                    "source_page_numbers": [page.page_number],
                    "citation_ids": sorted(page_cits[:3]),
                    "confidence": 0.7 if codes else 0.5,
                    "flags": flags,
                })

    # Stable sort: service_date, provider, amount, page
    lines.sort(key=lambda l: (
        l.get("service_date") or "",
        l.get("provider_entity_id") or "",
        l.get("amount", "0"),
        l.get("source_page_numbers", [0])[0] if l.get("source_page_numbers") else 0,
    ))

    return {
        "line_count": len(lines),
        "billing_pages_count": len(billing_pages),
        "lines": lines,
    }


# ── Artifact rendering ───────────────────────────────────────────────────

_CSV_COLUMNS = [
    "id", "provider_entity_id", "service_date", "post_date",
    "description", "code", "units", "amount", "amount_type",
    "source_page_numbers", "citation_ids", "confidence", "flags",
]


def generate_billing_lines_csv(lines: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for line in lines:
        row = dict(line)
        row["source_page_numbers"] = ";".join(str(p) for p in row.get("source_page_numbers", []))
        row["citation_ids"] = ";".join(row.get("citation_ids", []))
        row["flags"] = ";".join(row.get("flags", []))
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def generate_billing_lines_json(payload: dict) -> bytes:
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def render_billing_lines(
    run_id: str,
    payload: dict,
) -> tuple[Optional[ArtifactRef], Optional[ArtifactRef]]:
    """Save billing_lines artifacts."""
    lines = payload.get("lines", [])

    csv_bytes = generate_billing_lines_csv(lines)
    csv_path = save_artifact(run_id, "billing_lines.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    csv_ref = ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes))

    json_bytes = generate_billing_lines_json(payload)
    json_path = save_artifact(run_id, "billing_lines.json", json_bytes)
    json_sha = hashlib.sha256(json_bytes).hexdigest()
    json_ref = ArtifactRef(uri=str(json_path), sha256=json_sha, bytes=len(json_bytes))

    return csv_ref, json_ref
