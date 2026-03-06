from __future__ import annotations

import json
from pathlib import Path

from scripts.build_launch_acceptance_matrix import build_matrix


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_matrix_marks_narrow_pilot_ready_but_broad_launch_blocked(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reference" / "pass_057" / "cloud_batch30_rerun_20260306" / "summary.json",
        {
            "count": 30,
            "status_counts": {"success": 30},
            "runs": [{"exports_latest_status_code": 200} for _ in range(30)],
        },
    )
    _write_json(
        tmp_path / "reference" / "run_c0e611f937cf4292a328ada3cf57d74b_evidence_graph.json",
        {
            "extensions": {
                "renderer_manifest": {
                    "top_case_drivers": [],
                    "promoted_findings": [],
                    "case_skeleton": {"active": True},
                }
            }
        },
    )
    _write_json(
        tmp_path / "reference" / "pass_063" / "summary.json",
        {
            "result": {"validated_packets": 3, "ocr_positive_packets": 3},
            "packets": [
                {"packet": "packet_synthetic_image_only.pdf", "events_total": 2},
                {"packet": "packet_noisy_corpus_08_soft_tissue_noisy.pdf", "events_total": 9},
                {"packet": "packet_mimic_10002930_rasterized_clean.pdf", "status": "needs_review", "pages_total": 5, "pages_ocr": 1, "events_total": 0},
            ],
            "open_issue": "rasterized scans still timeout",
        },
    )
    _write_json(
        tmp_path / "reference" / "pass_064" / "summary.json",
        {
            "packets": [
                {"events_total": 8},
                {"events_total": 9},
                {"events_total": 14},
                {"events_total": 11},
            ]
        },
    )
    _write_json(
        tmp_path / "reference" / "pass_065" / "summary.json",
        {
            "result": {"event_counts_preserved": True, "office_visit_packets": 3},
            "packets": [
                {"events_total": 8},
                {"events_total": 14},
                {"events_total": 11},
            ],
        },
    )

    matrix = build_matrix(tmp_path)

    assert matrix["overall"]["recommended_launch_scope"] == "narrow_pilot"
    assert matrix["overall"]["narrow_pilot_ready"] is True
    assert matrix["overall"]["broad_launch_ready"] is False
    rasterized = next(d for d in matrix["dimensions"] if d["key"] == "fully_rasterized_scan_packets")
    assert rasterized["status"] == "blocked"
