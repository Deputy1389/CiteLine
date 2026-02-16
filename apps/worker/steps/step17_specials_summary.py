"""
Step 17 — Specials Summary (Phase 5).

Computes conservative, auditable billing totals from billing_lines.
Includes deduplication, per-provider breakdown, and coverage metrics.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from packages.shared.models import ArtifactRef
from packages.shared.storage import save_artifact


def _dedupe_key(line: dict) -> str:
    """
    Generate a deduplication key for a billing line.
    key = (provider_entity_id, service_date, code, amount, description_hash)
    """
    desc = (line.get("description") or "").strip().lower()[:80]
    parts = [
        line.get("provider_entity_id") or "",
        line.get("service_date") or "",
        line.get("code") or "",
        line.get("amount") or "0",
        desc,
    ]
    return "|".join(parts)


def _to_decimal(val) -> Decimal:
    """Safely convert to Decimal."""
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def compute_specials_summary(
    billing_lines_payload: dict,
    providers_normalized: list[dict],
) -> dict:
    """
    Compute specials summary from billing lines.
    Returns extensions payload for specials_summary.
    """
    lines = billing_lines_payload.get("lines", [])
    billing_pages_count = billing_lines_payload.get("billing_pages_count", 0)

    if not lines:
        return {
            "totals": {
                "total_charges": "0.00",
                "total_payments": None,
                "total_adjustments": None,
                "total_balance": None,
            },
            "by_provider": [],
            "coverage": {
                "earliest_service_date": None,
                "latest_service_date": None,
                "billing_pages_count": billing_pages_count,
            },
            "dedupe": {
                "strategy": "keyed_hash",
                "lines_raw": 0,
                "lines_deduped": 0,
            },
            "confidence": 0.0,
            "flags": ["NO_BILLING_DATA"],
        }

    # ── Deduplication ─────────────────────────────────────────────────
    seen_keys: set[str] = set()
    deduped_lines: list[dict] = []
    for line in lines:
        key = _dedupe_key(line)
        if key not in seen_keys:
            seen_keys.add(key)
            deduped_lines.append(line)

    # ── Aggregation ───────────────────────────────────────────────────
    total_charges = Decimal("0.00")
    total_payments = Decimal("0.00")
    total_adjustments = Decimal("0.00")
    total_balance = Decimal("0.00")
    has_payments = False
    has_adjustments = False
    has_balance = False

    # Per-provider accumulators
    provider_buckets: dict[str, dict] = {}

    all_dates: list[str] = []
    all_cit_ids: set[str] = set()

    for line in deduped_lines:
        amount = _to_decimal(line.get("amount", "0"))
        atype = line.get("amount_type", "unknown")
        provider = line.get("provider_entity_id") or "__unresolved__"

        if provider not in provider_buckets:
            provider_buckets[provider] = {
                "charges": Decimal("0.00"),
                "payments": Decimal("0.00"),
                "adjustments": Decimal("0.00"),
                "balance": Decimal("0.00"),
                "line_count": 0,
                "cit_ids": set(),
                "flags": set(),
            }

        bucket = provider_buckets[provider]
        bucket["line_count"] += 1

        for cid in line.get("citation_ids", []):
            all_cit_ids.add(cid)
            bucket["cit_ids"].add(cid)

        if line.get("service_date"):
            all_dates.append(line["service_date"])

        if atype in ("charge", "unknown"):
            total_charges += amount
            bucket["charges"] += amount
        elif atype in ("payment", "copay", "coinsurance"):
            total_payments += amount
            bucket["payments"] += amount
            has_payments = True
        elif atype in ("adjustment", "writeoff"):
            total_adjustments += amount
            bucket["adjustments"] += amount
            has_adjustments = True
        elif atype in ("balance", "deductible"):
            total_balance += amount
            bucket["balance"] += amount
            has_balance = True

        if line.get("flags"):
            for f in line["flags"]:
                bucket["flags"].add(f)

    # ── Build per-provider output ─────────────────────────────────────
    # Build display name lookup
    norm_to_display: dict[str, str] = {}
    for entity in providers_normalized:
        norm_to_display[entity["normalized_name"]] = entity["display_name"]

    by_provider = []
    for provider, bkt in sorted(provider_buckets.items()):
        display = norm_to_display.get(provider, provider)
        if provider == "__unresolved__":
            display = "Unresolved Provider"

        provider_total = bkt["charges"] + bkt["payments"] + bkt["adjustments"] + bkt["balance"]
        conf = 0.7 if bkt["line_count"] > 0 else 0.0
        if "PROVIDER_UNRESOLVED" in bkt["flags"]:
            conf *= 0.8

        by_provider.append({
            "provider_entity_id": provider if provider != "__unresolved__" else None,
            "provider_display_name": display,
            "charges": str(bkt["charges"].quantize(Decimal("0.01"))),
            "payments": str(bkt["payments"].quantize(Decimal("0.01"))) if has_payments else None,
            "adjustments": str(bkt["adjustments"].quantize(Decimal("0.01"))) if has_adjustments else None,
            "balance": str(bkt["balance"].quantize(Decimal("0.01"))) if has_balance else None,
            "line_count": bkt["line_count"],
            "confidence": round(conf, 2),
            "flags": sorted(bkt["flags"]),
            "citation_ids_sample": sorted(bkt["cit_ids"])[:5],
        })

    # ── Flags ─────────────────────────────────────────────────────────
    flags = []
    if not has_payments:
        flags.append("MISSING_EOB_DATA")
    if not has_adjustments:
        flags.append("PARTIAL_BILLING_ONLY")

    # Date coverage
    sorted_dates = sorted(all_dates)
    earliest = sorted_dates[0] if sorted_dates else None
    latest = sorted_dates[-1] if sorted_dates else None

    # Overall confidence
    overall_conf = 0.7
    if len(flags) > 0:
        overall_conf *= 0.8
    if len(deduped_lines) < len(lines):
        overall_conf *= 0.95  # Slight penalty for heavy duplication

    return {
        "totals": {
            "total_charges": str(total_charges.quantize(Decimal("0.01"))),
            "total_payments": str(total_payments.quantize(Decimal("0.01"))) if has_payments else None,
            "total_adjustments": str(total_adjustments.quantize(Decimal("0.01"))) if has_adjustments else None,
            "total_balance": str(total_balance.quantize(Decimal("0.01"))) if has_balance else None,
        },
        "by_provider": by_provider,
        "coverage": {
            "earliest_service_date": earliest,
            "latest_service_date": latest,
            "billing_pages_count": billing_pages_count,
        },
        "dedupe": {
            "strategy": "keyed_hash",
            "lines_raw": len(lines),
            "lines_deduped": len(deduped_lines),
        },
        "confidence": round(overall_conf, 2),
        "flags": flags,
    }


# ── Artifact rendering ───────────────────────────────────────────────────

_CSV_COLUMNS = [
    "provider_display_name", "provider_entity_id",
    "charges", "payments", "adjustments", "balance",
    "line_count", "confidence", "flags",
]


def generate_specials_csv(summary: dict) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for provider in summary.get("by_provider", []):
        row = dict(provider)
        row["flags"] = ";".join(row.get("flags", []))
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def generate_specials_json(summary: dict) -> bytes:
    return json.dumps(summary, indent=2, default=str).encode("utf-8")


def render_specials_summary(
    run_id: str,
    summary: dict,
) -> tuple[Optional[ArtifactRef], Optional[ArtifactRef]]:
    """Save specials_summary artifacts."""
    csv_bytes = generate_specials_csv(summary)
    csv_path = save_artifact(run_id, "specials_summary.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    csv_ref = ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes))

    json_bytes = generate_specials_json(summary)
    json_path = save_artifact(run_id, "specials_summary.json", json_bytes)
    json_sha = hashlib.sha256(json_bytes).hexdigest()
    json_ref = ArtifactRef(uri=str(json_path), sha256=json_sha, bytes=len(json_bytes))

    return csv_ref, json_ref
