from __future__ import annotations

from apps.worker.lib.pipeline_parity import build_pipeline_parity_report


def test_build_pipeline_parity_report_shape() -> None:
    report = build_pipeline_parity_report(
        mode="production",
        source_pdf="C:/tmp/input.pdf",
        page_text_by_number={1: "hello"},
        projection_entries=[{"event_id": "e1"}],
        chronology_events=[{"event_id": "e1"}],
        gaps=[{"gap_id": "g1"}],
        gate_results={"overall_pass": False, "failures": [{"code": "X"}]},
    )
    assert report["schema_version"] == "pipeline_parity.v1"
    assert report["mode"] == "production"
    assert report["canonical_quality_gate_api"] == "apps.worker.lib.quality_gates.run_quality_gates"
    assert report["intentional_deltas"] == []
    assert report["eval_run_quality_gates_kwargs"]["projection_entries"] == 1
    assert report["eval_run_quality_gates_kwargs"]["chronology_events"] == 1
    assert report["eval_run_quality_gates_kwargs"]["gaps"] == 1
    assert report["gate_outcome_snapshot"]["overall_pass"] is False
    assert report["gate_outcome_snapshot"]["failures_count"] == 1
    assert report["gate_outcome_snapshot"]["failure_codes"] == ["X"]


def test_build_pipeline_parity_report_stable_failure_codes_with_source() -> None:
    report = build_pipeline_parity_report(
        mode="eval",
        source_pdf=None,
        page_text_by_number={},
        projection_entries=[],
        chronology_events=[],
        gaps=[],
        gate_results={
            "overall_pass": False,
            "failures": [
                {"source": "luqa", "code": "L1"},
                {"source": "luqa", "code": "L1"},
                {"source": "attorney", "code": "A2"},
            ],
        },
    )
    assert report["gate_outcome_snapshot"]["failure_codes"] == ["luqa:L1", "attorney:A2"]
