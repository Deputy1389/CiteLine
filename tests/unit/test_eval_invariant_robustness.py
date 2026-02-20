from __future__ import annotations

import random
from pathlib import Path

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from scripts.eval_invariant_robustness import (
    Snapshot,
    _compare_invariants,
    _drop_random_pages,
    _inject_noise,
    _mix_packets,
    _shuffle_pages,
)


def _make_pdf(path: Path, pages: int, prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    for i in range(1, pages + 1):
        c.setFont("Helvetica", 12)
        c.drawString(72, 720, f"{prefix} page {i}")
        c.showPage()
    c.save()


def _page_texts(path: Path) -> list[str]:
    r = PdfReader(str(path))
    return [(p.extract_text() or "").strip() for p in r.pages]


def test_shuffle_pages_is_deterministic_for_seed(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_pdf(src, pages=6, prefix="A")
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _shuffle_pages(src, a, random.Random(7))
    _shuffle_pages(src, b, random.Random(7))
    assert _page_texts(a) == _page_texts(b)
    assert len(_page_texts(a)) == 6


def test_drop_random_pages_reduces_count(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_pdf(src, pages=8, prefix="B")
    out = tmp_path / "drop.pdf"
    _drop_random_pages(src, out, random.Random(11), drop_ratio=0.5)
    assert len(PdfReader(str(out)).pages) == 4


def test_inject_noise_keeps_page_count(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    _make_pdf(src, pages=5, prefix="C")
    out = tmp_path / "noise.pdf"
    _inject_noise(src, out, random.Random(13), noise_page_ratio=0.4)
    assert len(PdfReader(str(out)).pages) == 5


def test_mix_packets_interleaves_sources(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _make_pdf(a, pages=3, prefix="A")
    _make_pdf(b, pages=3, prefix="B")
    out = tmp_path / "mix.pdf"
    _mix_packets(a, b, out, random.Random(5))
    texts = " ".join(_page_texts(out))
    assert "A page" in texts
    assert "B page" in texts
    assert len(PdfReader(str(out)).pages) == 6


def test_compare_invariants_flags_material_change() -> None:
    base = Snapshot(
        case_id="base",
        run_id="r1",
        source_pdf="a.pdf",
        source_pages=10,
        qa_pass=True,
        legal_pass=True,
        overall_pass=True,
        projection_entry_count=10,
        gaps_count=1,
        timeline_rows=10,
        timeline_citation_coverage=1.0,
        required_buckets_present=("ed", "pt_eval"),
        hard_failure_codes=(),
        csv_rows=10,
        csv_dated_rows=9,
        csv_date_parse_ratio=0.9,
    )
    pert = Snapshot(
        case_id="pert",
        run_id="r2",
        source_pdf="b.pdf",
        source_pages=10,
        qa_pass=False,
        legal_pass=True,
        overall_pass=False,
        projection_entry_count=2,
        gaps_count=1,
        timeline_rows=2,
        timeline_citation_coverage=0.5,
        required_buckets_present=("pt_eval",),
        hard_failure_codes=("HIGH_RISK_UNANCHORED",),
        csv_rows=2,
        csv_dated_rows=0,
        csv_date_parse_ratio=0.0,
    )
    cmp = _compare_invariants(base, pert, perturbation="shuffle_order")
    assert cmp["material_change"] is True
    assert cmp["checks"]["citation_anchor_floor"] is False
