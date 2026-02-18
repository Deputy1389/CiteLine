from __future__ import annotations

from scripts.eval_mega_stress import evaluate_mega_stress


def test_eval_mega_stress_output_quality():
    score = evaluate_mega_stress()
    assert score["overall_pass"] is True
    assert score["contains_date_not_documented_pt_visit"] is False
    assert score["contains_provider_lines"] is False
    assert score["contains_encounter_fallback"] is False
    assert score["contains_gunshot"] is False
    assert score["timeline_rows"] < 80
