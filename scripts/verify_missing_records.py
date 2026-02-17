"""
Step 8 — Developer verification script for Missing Record Detection.

Loads the latest EvidenceGraph (via database or most recent run) 
and prints a summary of detected gaps.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from packages.db.database import get_session
from packages.db.models import Run, Artifact

def verify_latest_run():
    with get_session() as session:
        # Find latest successful or partial run
        latest_run = (
            session.query(Run)
            .filter(Run.status.in_(["success", "partial"]))
            .order_by(Run.finished_at.desc())
            .first()
        )

        if not latest_run:
            print("No successful runs found.")
            return

        print(f"Verifying Run: {latest_run.id} ({latest_run.finished_at})")

        # Find evidence_graph.json artifact
        artifact = (
            session.query(Artifact)
            .filter_by(run_id=latest_run.id, artifact_type="json")
            .first()
        )

        if not artifact:
            print("EvidenceGraph JSON artifact not found for this run.")
            return

        storage_path = Path(artifact.storage_uri)
        if not storage_path.exists():
            print(f"Artifact file does not exist at: {storage_path}")
            return

        with open(storage_path, "r") as f:
            data = json.load(f)

        # Extract missing_records from extensions
        eg = data.get("outputs", {}).get("evidence_graph", {})
        missing_records = eg.get("extensions", {}).get("missing_records", {})

        if not missing_records:
            print("No missing_records found in EvidenceGraph extensions.")
            return

        summary = missing_records.get("summary", {})
        gaps = missing_records.get("gaps", [])

        print("-" * 40)
        print(f"Total gaps:          {summary.get('total_gaps', 0)}")
        print(f"Provider gaps:       {summary.get('provider_gap_count', 0)}")
        print(f"Global gaps:         {summary.get('global_gap_count', 0)}")
        print(f"High severity:       {summary.get('high_severity_count', 0)}")
        print(f"Medium severity:     {summary.get('medium_severity_count', 0)}")
        print("-" * 40)

        # Top 5 largest gaps
        sorted_gaps = sorted(gaps, key=lambda x: x.get("gap_days", 0), reverse=True)
        print("Top 5 largest gaps:")
        for i, gap in enumerate(sorted_gaps[:5]):
            provider = gap.get("provider_display_name") or "GLOBAL"
            print(f"{i+1}. {gap['gap_days']} days | {provider} | {gap['start_date']} to {gap['end_date']} | {gap['severity']}")

if __name__ == "__main__":
    verify_latest_run()
