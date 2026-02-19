from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_case as rc


def test_run_case_uses_checklist_as_single_pass_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    rendered_pdf = tmp_path / "rendered.pdf"
    rendered_pdf.write_bytes(b"%PDF-1.4\n%fake\n")

    monkeypatch.setattr(rc, "ROOT", tmp_path)
    monkeypatch.setattr(rc, "run_sample_pipeline", lambda input_pdf, run_id: (rendered_pdf, {"projection_entries": [], "gaps_count": 0}))
    monkeypatch.setattr(rc, "extract_pdf_text", lambda p: "report text")
    monkeypatch.setattr(rc, "score_report", lambda txt, ctx: {"overall_pass": True, "model_score": 77})
    monkeypatch.setattr(
        rc,
        "build_litigation_checklist",
        lambda **kwargs: {"pass": False, "score_0_100": 65, "failure_summary": {"hard_failed": True, "quality_failed": False, "contract_failed": False}},
    )
    monkeypatch.setattr(rc, "write_litigation_checklist", lambda path, checklist: path.write_text(json.dumps(checklist), encoding="utf-8"))
    monkeypatch.setattr(rc, "_write_qafail_cover_pdf", lambda out_pdf, checklist: None)

    payload = rc.run_case(input_pdf=input_pdf, case_id="case1", run_label="run1")
    assert payload["overall_pass"] is False
    scorecard_path = tmp_path / "data" / "evals" / "case1" / "scorecard.json"
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    assert scorecard["overall_pass"] is False
    assert scorecard["score_0_100"] == 65
    assert scorecard["qa_pass"] is False

