from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_case as rc


def test_run_case_uses_quality_gates_as_single_pass_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    rendered_pdf = tmp_path / "rendered.pdf"
    rendered_pdf.write_bytes(b"%PDF-1.4\n%fake\n")

    monkeypatch.setattr(rc, "ROOT", tmp_path)
    monkeypatch.setattr(rc, "run_sample_pipeline", lambda input_pdf, run_id, **kwargs: (rendered_pdf, {"projection_entries": [], "gaps_count": 0}))
    monkeypatch.setattr(rc, "extract_pdf_text", lambda p: "report text")
    monkeypatch.setattr(rc, "score_report", lambda txt, ctx: {"overall_pass": True, "model_score": 77})
    monkeypatch.setattr(
        rc,
        "build_litigation_checklist",
        lambda **kwargs: {"pass": False, "score_0_100": 65, "failure_summary": {"hard_failed": True, "quality_failed": False, "contract_failed": False}},
    )
    monkeypatch.setattr(
        rc,
        "run_quality_gates",
        lambda **kwargs: {
            "overall_pass": True,
            "attorney_ready_pass": True,
            "attorney_ready_score": 95,
            "luqa_pass": True,
            "luqa_score": 95,
            "gate_report": {
                "luqa": {"luqa_pass": True, "luqa_score_0_100": 95, "failures": [], "metrics": {}},
                "attorney": {"attorney_ready_pass": True, "attorney_ready_score_0_100": 95, "failures": [], "metrics": {}},
            },
            "failures": [],
        },
    )
    monkeypatch.setattr(rc, "write_litigation_checklist", lambda path, checklist: path.write_text(json.dumps(checklist), encoding="utf-8"))
    monkeypatch.setattr(rc, "write_fail_cover_pdf", lambda out_pdf, gate_results: False)

    payload = rc.run_case(input_pdf=input_pdf, case_id="case1", run_label="run1", export_mode="INTERNAL")
    assert payload["overall_pass"] is True
    assert payload["qa_pass"] is True
    assert payload["pipeline_parity_report"]["intentional_deltas"] == []
    scorecard_path = tmp_path / "data" / "evals" / "case1" / "scorecard.json"
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    assert scorecard["overall_pass"] is True
    assert scorecard["score_0_100"] == 65
    assert scorecard["qa_pass"] is True
    parity_path = tmp_path / "data" / "evals" / "case1" / "pipeline_parity_report.json"
    assert parity_path.exists()


def test_run_case_requires_luqa_and_qa_for_overall_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    rendered_pdf = tmp_path / "rendered.pdf"
    rendered_pdf.write_bytes(b"%PDF-1.4\n%fake\n")

    monkeypatch.setattr(rc, "ROOT", tmp_path)
    monkeypatch.setattr(rc, "run_sample_pipeline", lambda input_pdf, run_id, **kwargs: (rendered_pdf, {"projection_entries": [], "gaps_count": 0}))
    monkeypatch.setattr(rc, "extract_pdf_text", lambda p: "report text")
    monkeypatch.setattr(rc, "score_report", lambda txt, ctx: {"overall_pass": True, "model_score": 77})
    monkeypatch.setattr(
        rc,
        "build_litigation_checklist",
        lambda **kwargs: {"pass": True, "score_0_100": 99, "failure_summary": {"hard_failed": False, "quality_failed": False, "contract_failed": False}},
    )
    monkeypatch.setattr(
        rc,
        "run_quality_gates",
        lambda **kwargs: {
            "overall_pass": False,
            "attorney_ready_pass": True,
            "attorney_ready_score": 98,
            "luqa_pass": False,
            "luqa_score": 55,
            "gate_report": {
                "luqa": {"luqa_pass": False, "luqa_score_0_100": 55, "failures": [{"code": "X"}], "metrics": {}},
                "attorney": {"attorney_ready_pass": True, "attorney_ready_score_0_100": 98, "failures": [], "metrics": {}},
            },
            "failures": [{"source": "luqa", "code": "X"}],
        },
    )
    monkeypatch.setattr(rc, "write_litigation_checklist", lambda path, checklist: path.write_text(json.dumps(checklist), encoding="utf-8"))
    monkeypatch.setattr(rc, "write_fail_cover_pdf", lambda out_pdf, gate_results: False)

    payload = rc.run_case(input_pdf=input_pdf, case_id="case2", run_label="run2", export_mode="INTERNAL")
    assert payload["overall_pass"] is False
    assert payload["qa_pass"] is False
    assert payload["luqa_pass"] is False
    scorecard_path = tmp_path / "data" / "evals" / "case2" / "scorecard.json"
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    assert scorecard["overall_pass"] is False
    assert scorecard["qa_pass"] is False
    assert scorecard["luqa_pass"] is False


def test_run_case_requires_attorney_readiness_for_overall_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    rendered_pdf = tmp_path / "rendered.pdf"
    rendered_pdf.write_bytes(b"%PDF-1.4\n%fake\n")

    monkeypatch.setattr(rc, "ROOT", tmp_path)
    monkeypatch.setattr(rc, "run_sample_pipeline", lambda input_pdf, run_id, **kwargs: (rendered_pdf, {"projection_entries": [], "gaps_count": 0}))
    monkeypatch.setattr(rc, "extract_pdf_text", lambda p: "report text")
    monkeypatch.setattr(rc, "score_report", lambda txt, ctx: {"overall_pass": True, "model_score": 90})
    monkeypatch.setattr(
        rc,
        "build_litigation_checklist",
        lambda **kwargs: {"pass": True, "score_0_100": 100, "failure_summary": {"hard_failed": False, "quality_failed": False, "contract_failed": False}},
    )
    monkeypatch.setattr(
        rc,
        "run_quality_gates",
        lambda **kwargs: {
            "overall_pass": False,
            "attorney_ready_pass": False,
            "attorney_ready_score": 60,
            "luqa_pass": True,
            "luqa_score": 100,
            "gate_report": {
                "luqa": {"luqa_pass": True, "luqa_score_0_100": 100, "failures": [], "metrics": {}},
                "attorney": {"attorney_ready_pass": False, "attorney_ready_score_0_100": 60, "failures": [{"code": "AR_FAIL"}], "metrics": {}},
            },
            "failures": [{"source": "attorney", "code": "AR_FAIL"}],
        },
    )
    monkeypatch.setattr(rc, "write_litigation_checklist", lambda path, checklist: path.write_text(json.dumps(checklist), encoding="utf-8"))
    monkeypatch.setattr(rc, "write_fail_cover_pdf", lambda out_pdf, gate_results: False)

    payload = rc.run_case(input_pdf=input_pdf, case_id="case3", run_label="run3", export_mode="INTERNAL")
    assert payload["overall_pass"] is False
    assert payload["qa_pass"] is False
    assert payload["luqa_pass"] is True
    assert payload["attorney_ready_pass"] is False


def test_run_case_requires_export_mode_argument(tmp_path: Path):
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    with pytest.raises(ValueError, match="export_mode is required"):
        rc.run_case(input_pdf=input_pdf, case_id="case4", run_label="run4", export_mode=None)
