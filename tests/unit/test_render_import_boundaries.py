from __future__ import annotations

import re
from pathlib import Path


def test_client_renderer_does_not_import_atom_layer():
    src = Path("apps/worker/steps/step12_export.py").read_text(encoding="utf-8")
    forbidden = [
        "ClinicalAtom",
        "synthesis_domain",
        "event_to_atoms",
        "cluster_atoms_into_events",
        "extract_fields",
        "atoms.jsonl",
    ]
    for token in forbidden:
        assert token not in src, f"Renderer must not depend on atom layer token: {token}"


def test_renderer_uses_projection_contract():
    src = Path("apps/worker/steps/step12_export.py").read_text(encoding="utf-8")
    assert "build_chronology_projection(" in src
    assert re.search(r"generate_pdf_from_projection\(", src)
