"""
Unit tests for Step 15a - Missing Record Request Generator.
"""
from __future__ import annotations

import csv
import io
import json

from apps.worker.steps.step15a_missing_record_requests import (
    generate_missing_record_requests,
    generate_missing_record_requests_csv,
    generate_missing_record_requests_json,
)
from packages.shared.models import EvidenceGraph


def _graph_with_gaps(gaps: list[dict]) -> EvidenceGraph:
    return EvidenceGraph(
        extensions={
            "missing_records": {
                "version": "1.0",
                "generated_at": "2026-02-17T00:00:00+00:00",
                "gaps": gaps,
            }
        }
    )


def test_single_gap_single_request():
    graph = _graph_with_gaps([
        {
            "gap_id": "gap-1",
            "provider_id": "p1",
            "provider_display_name": "LSU Public Hospital",
            "start_date": "2023-01-01",
            "end_date": "2023-02-01",
            "gap_days": 31,
            "severity": "medium",
        }
    ])

    result = generate_missing_record_requests(graph)
    requests = result["requests"]
    assert len(requests) == 1
    req = requests[0]
    assert req["provider_id"] == "p1"
    assert req["request_date_range"]["from_date"] == "2023-01-01"
    assert req["request_date_range"]["to_date"] == "2023-02-01"
    assert req["request_priority"] == "standard"
    assert req["gap_reference"]["gap_id"] == "gap-1"


def test_multiple_gaps_same_provider_merged_request():
    graph = _graph_with_gaps([
        {
            "gap_id": "gap-a",
            "provider_id": "p1",
            "provider_display_name": "LSU Public Hospital",
            "start_date": "2023-01-01",
            "end_date": "2023-02-01",
            "gap_days": 31,
            "severity": "medium",
        },
        {
            "gap_id": "gap-b",
            "provider_id": "p1",
            "provider_display_name": "LSU Public Hospital",
            "start_date": "2023-02-02",
            "end_date": "2023-03-01",
            "gap_days": 27,
            "severity": "high",
        },
    ])

    result = generate_missing_record_requests(graph)
    requests = result["requests"]
    assert len(requests) == 1
    req = requests[0]
    assert req["request_date_range"]["from_date"] == "2023-01-01"
    assert req["request_date_range"]["to_date"] == "2023-03-01"
    assert req["request_priority"] == "urgent"


def test_determinism_across_runs():
    graph = _graph_with_gaps([
        {
            "gap_id": "gap-1",
            "provider_id": "p2",
            "provider_display_name": "Alpha Clinic",
            "start_date": "2023-05-01",
            "end_date": "2023-06-15",
            "gap_days": 45,
            "severity": "medium",
        },
        {
            "gap_id": "gap-2",
            "provider_id": "p1",
            "provider_display_name": "Beta Health",
            "start_date": "2023-01-01",
            "end_date": "2023-04-15",
            "gap_days": 104,
            "severity": "high",
        },
    ])

    r1 = generate_missing_record_requests(graph)
    r2 = generate_missing_record_requests(graph)
    r1.pop("generated_at")
    r2.pop("generated_at")
    assert r1 == r2


def test_csv_and_json_consistency():
    graph = _graph_with_gaps([
        {
            "gap_id": "gap-1",
            "provider_id": "p1",
            "provider_display_name": "LSU Public Hospital",
            "start_date": "2023-01-01",
            "end_date": "2023-02-01",
            "gap_days": 31,
            "severity": "medium",
        }
    ])
    payload = generate_missing_record_requests(graph)

    json_payload = json.loads(generate_missing_record_requests_json(payload).decode("utf-8"))
    csv_text = generate_missing_record_requests_csv(payload).decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert len(rows) == len(json_payload["requests"]) == 1
    row = rows[0]
    req = json_payload["requests"][0]
    assert row["request_id"] == req["request_id"]
    assert row["provider_id"] == req["provider_id"]
    assert row["from_date"] == req["request_date_range"]["from_date"]
    assert row["to_date"] == req["request_date_range"]["to_date"]
    assert row["priority"] == req["request_priority"]
