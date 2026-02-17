from __future__ import annotations

from pathlib import Path


def test_runs_route_uses_shared_artifact_registry():
    src = Path("apps/api/routes/runs.py").read_text(encoding="utf-8")
    assert "from packages.shared.artifacts import" in src
    assert "valid_types = [" not in src
    assert "extension_map = {" not in src


def test_pipeline_uses_artifact_entry_builder():
    src = Path("apps/worker/pipeline.py").read_text(encoding="utf-8")
    assert "build_artifact_ref_entries(" in src
    assert "persist_pipeline_state(" in src
