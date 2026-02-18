from __future__ import annotations

from pathlib import Path

import fitz

from scripts.generate_chaos_packets import _plan_indices, generate_chaos_packets


def _create_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Patient Name: Test{i} User{i}\nDate: 2024-01-0{i+1}")
    doc.save(str(path))
    doc.close()


def test_plan_indices_deterministic():
    import random

    r1 = random.Random(123)
    r2 = random.Random(123)
    assert _plan_indices(10, "mild", r1) == _plan_indices(10, "mild", r2)


def test_generate_chaos_packets_smoke(tmp_path: Path):
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir(parents=True)
    _create_pdf(src / "alpha.pdf", pages=4)

    summary = generate_chaos_packets(source_dir=src, output_dir=out, max_sources=1, seed=2026)
    assert summary["selected_sources"] == 1
    assert summary["generated_packets"] == 3
    manifest = out / "manifest.json"
    assert manifest.exists()
    for tier in ("mild", "moderate", "severe"):
        matches = list((out / tier).glob("*.pdf"))
        assert len(matches) == 1
