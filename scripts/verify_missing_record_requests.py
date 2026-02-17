"""
Developer verification script for Missing Record Requests.

Loads the latest EvidenceGraph and prints:
- Total providers with missing requests
- Total requests
- Top 5 providers by missing duration
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from packages.db.database import get_session
from packages.db.models import Artifact, Run


def verify_latest_run() -> None:
    with get_session() as session:
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

        with open(storage_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    eg = data.get("outputs", {}).get("evidence_graph", {})
    payload = eg.get("extensions", {}).get("missing_record_requests", {})
    requests = payload.get("requests", [])

    if not requests:
        print("No missing_record_requests found in EvidenceGraph extensions.")
        return

    providers = {r.get("provider_id") for r in requests if r.get("provider_id")}
    provider_days: dict[str, int] = defaultdict(int)
    provider_name: dict[str, str] = {}
    for req in requests:
        pid = req.get("provider_id")
        if not pid:
            continue
        provider_name[pid] = req.get("provider_display_name") or pid
        from_date = req.get("request_date_range", {}).get("from_date")
        to_date = req.get("request_date_range", {}).get("to_date")
        days = 0
        if from_date and to_date:
            days = (date.fromisoformat(to_date) - date.fromisoformat(from_date)).days
        provider_days[pid] += days

    print("-" * 48)
    print(f"Total providers with missing requests: {len(providers)}")
    print(f"Total requests: {len(requests)}")
    print("-" * 48)
    print("Top 5 providers by missing duration:")
    top = sorted(provider_days.items(), key=lambda kv: (-kv[1], provider_name.get(kv[0], kv[0])))[:5]
    for idx, (pid, total_days) in enumerate(top, start=1):
        print(f"{idx}. {provider_name.get(pid, pid)} ({pid}) - {total_days} days")


if __name__ == "__main__":
    verify_latest_run()
