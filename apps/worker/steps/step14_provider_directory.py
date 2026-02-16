"""
Step 14 — Provider Directory artifact generation (Phase 2).

Generates provider_directory.csv and provider_directory.json from normalized
provider entities. No new extraction — purely derived from the evidence graph.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Optional

from packages.shared.models import ArtifactRef
from packages.shared.storage import save_artifact


_CSV_COLUMNS = [
    "provider_display_name",
    "provider_type",
    "first_seen_date",
    "last_seen_date",
    "event_count",
    "citation_count",
]


def generate_provider_directory_csv(entities: list[dict]) -> bytes:
    """Generate a CSV provider directory."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()

    for entity in entities:
        writer.writerow({
            "provider_display_name": entity.get("display_name", ""),
            "provider_type": entity.get("provider_type", "unknown"),
            "first_seen_date": entity.get("first_seen_date", ""),
            "last_seen_date": entity.get("last_seen_date", ""),
            "event_count": entity.get("event_count", 0),
            "citation_count": entity.get("citation_count", 0),
        })

    return buf.getvalue().encode("utf-8")


def generate_provider_directory_json(entities: list[dict]) -> bytes:
    """Generate a JSON provider directory."""
    output = {
        "provider_directory_version": "1.0",
        "provider_count": len(entities),
        "providers": entities,
    }
    return json.dumps(output, indent=2, default=str).encode("utf-8")


def render_provider_directory(
    run_id: str,
    entities: list[dict],
) -> tuple[Optional[ArtifactRef], Optional[ArtifactRef]]:
    """
    Render provider directory artifacts and save to disk.
    Returns (csv_artifact_ref, json_artifact_ref).
    """
    if not entities:
        return None, None

    # CSV
    csv_bytes = generate_provider_directory_csv(entities)
    csv_path = save_artifact(run_id, "provider_directory.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    csv_ref = ArtifactRef(
        uri=str(csv_path),
        sha256=csv_sha,
        bytes=len(csv_bytes),
    )

    # JSON
    json_bytes = generate_provider_directory_json(entities)
    json_path = save_artifact(run_id, "provider_directory.json", json_bytes)
    json_sha = hashlib.sha256(json_bytes).hexdigest()
    json_ref = ArtifactRef(
        uri=str(json_path),
        sha256=json_sha,
        bytes=len(json_bytes),
    )

    return csv_ref, json_ref
