from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.litigation_qa import build_litigation_checklist


def test_qa_artifact_paths_exist_or_are_null_with_warning(tmp_path: Path):
    existing = tmp_path / "evidence_graph.json"
    existing.write_text("{}", encoding="utf-8")
    ctx = {
        "projection_entries": [
            SimpleNamespace(
                event_id="e1",
                event_type_display="Follow-Up Visit",
                facts=["Assessment: cervical pain."],
                citation_display="x.pdf p. 1",
                patient_label="P1",
                date_display="2025-01-01",
                provider_display="Unknown",
            )
        ],
        "events": [],
        "missing_records_payload": {"gaps": []},
        "page_text_by_number": {},
        "source_pages": 10,
        "patient_scope_violations": [],
        "artifact_manifest": {
            "evidence_graph.json": str(existing.resolve()),
            "missing_records.json": str((tmp_path / "missing_records.json").resolve()),  # missing on purpose
        },
    }
    checklist = build_litigation_checklist(
        run_id="r1",
        source_pdf="x.pdf",
        report_text="Top 10 Case-Driving Events\nAppendix E: Issue Flags",
        ctx=ctx,
        chronology_pdf_path=tmp_path / "out.pdf",
    )
    artifacts = checklist["artifacts"]
    assert artifacts["events_json"] is not None
    assert Path(artifacts["events_json"]).exists()
    assert artifacts["missing_records_report_json"] is None
    assert any("missing artifact:" in w for w in checklist.get("warnings", []))


def test_eval_bundle_contains_core_artifacts(monkeypatch, tmp_path: Path):
    import scripts.run_case as rc

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    rendered_pdf = tmp_path / "rendered.pdf"
    rendered_pdf.write_bytes(b"%PDF-1.4\n%fake\n")

    monkeypatch.setattr(rc, "ROOT", tmp_path)

    def _pipeline(_input, run_id):
        artifact_dir = tmp_path / "data" / "artifacts" / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for name in [
            "evidence_graph.json",
            "patient_partitions.json",
            "missing_records.json",
            "selection_debug.json",
            "claim_guard_report.json",
        ]:
            (artifact_dir / name).write_text("{}", encoding="utf-8")
        return rendered_pdf, {
            "projection_entries": [],
            "gaps_count": 0,
            "artifact_manifest": {name: str((artifact_dir / name).resolve()) for name in [
                "evidence_graph.json",
                "patient_partitions.json",
                "missing_records.json",
                "selection_debug.json",
                "claim_guard_report.json",
            ]},
        }

    monkeypatch.setattr(rc, "run_sample_pipeline", _pipeline)
    monkeypatch.setattr(rc, "extract_pdf_text", lambda p: "Top 10 Case-Driving Events\nAppendix E: Issue Flags")
    monkeypatch.setattr(rc, "score_report", lambda txt, ctx: {"overall_pass": True, "model_score": 77})
    monkeypatch.setattr(
        rc,
        "build_litigation_checklist",
        lambda **kwargs: {
            "pass": True,
            "score_0_100": 100,
            "failure_summary": {"hard_failed": False, "quality_failed": False, "contract_failed": False},
            "quality_gates": {},
            "hard_failures": [],
            "metrics": {},
            "artifacts": {
                "events_json": kwargs["ctx"]["artifact_manifest"].get("evidence_graph.json"),
                "patients_json": kwargs["ctx"]["artifact_manifest"].get("patient_partitions.json"),
                "missing_records_report_json": kwargs["ctx"]["artifact_manifest"].get("missing_records.json"),
            },
        },
    )
    monkeypatch.setattr(rc, "write_litigation_checklist", lambda path, checklist: path.write_text(json.dumps(checklist), encoding="utf-8"))
    monkeypatch.setattr(rc, "_write_qafail_cover_pdf", lambda out_pdf, checklist: None)

    rc.run_case(input_pdf=input_pdf, case_id="bundle", run_label="runbundle")
    eval_dir = tmp_path / "data" / "evals" / "bundle"
    assert (eval_dir / "evidence_graph.json").exists()
    assert (eval_dir / "patient_partitions.json").exists()
    assert (eval_dir / "missing_records.json").exists()
    assert (eval_dir / "selection_debug.json").exists()
    assert (eval_dir / "claim_guard_report.json").exists()
    assert (eval_dir / "semqa_debug.json").exists()

