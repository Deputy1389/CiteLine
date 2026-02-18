from __future__ import annotations

from pathlib import Path

from scripts.eval_sample_172 import evaluate_sample_172


def test_eval_sample_172_overall_pass():
    scorecard = evaluate_sample_172(debug_trace=False)
    assert scorecard["overall_pass"] is True
    assert scorecard["has_placeholder_dates"] is False
    assert scorecard["has_uuid_provider_ids"] is False
    assert scorecard["has_raw_fragment_dump"] is False
    assert scorecard["has_atom_dump_marker"] is False
    assert scorecard["has_date_not_documented_pt_visit"] is False
    assert scorecard["has_provider_lines_in_timeline"] is False
    assert scorecard["timeline_entry_count"] < 80
    assert scorecard["provider_misassignment_count"] == 0
    assert scorecard["patient_scope_violation_count"] == 0
    assert scorecard["total_surgeries_field"] == 2
    assert scorecard["debug_trace_written"] is False
    assert not Path("data/evals/sample_172/evidence_trace.json").exists()


def test_eval_sample_172_debug_trace_opt_in():
    scorecard = evaluate_sample_172(debug_trace=True)
    assert scorecard["debug_trace_written"] is True
    assert Path("data/evals/sample_172/evidence_trace.json").exists()
