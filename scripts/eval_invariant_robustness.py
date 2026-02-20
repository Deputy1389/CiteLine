from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_case import run_case


DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


@dataclass(frozen=True)
class Snapshot:
    case_id: str
    run_id: str
    source_pdf: str
    source_pages: int
    qa_pass: bool
    legal_pass: bool
    overall_pass: bool
    projection_entry_count: int
    gaps_count: int
    timeline_rows: int
    timeline_citation_coverage: float
    required_buckets_present: tuple[str, ...]
    hard_failure_codes: tuple[str, ...]
    csv_rows: int
    csv_dated_rows: int
    csv_date_parse_ratio: float


def _page_count(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def _stable_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _discover_seed_pdfs(input_dir: Path, limit: int, seed: int) -> list[Path]:
    all_pdfs = sorted(p for p in input_dir.rglob("*.pdf") if p.is_file())
    if not all_pdfs:
        raise FileNotFoundError(f"No PDFs found under {input_dir}")
    rng = random.Random(seed)
    if len(all_pdfs) <= limit:
        return all_pdfs
    # Sample deterministically so harness is not tied to file naming/layout.
    chosen = rng.sample(all_pdfs, limit)
    return sorted(chosen)


def _write_pdf(pages: list, out_path: Path) -> None:
    writer = PdfWriter()
    for p in pages:
        writer.add_page(p)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        writer.write(f)


def _shuffle_pages(src: Path, out_path: Path, rng: random.Random) -> None:
    reader = PdfReader(str(src))
    pages = list(reader.pages)
    rng.shuffle(pages)
    _write_pdf(pages, out_path)


def _drop_random_pages(src: Path, out_path: Path, rng: random.Random, drop_ratio: float) -> None:
    reader = PdfReader(str(src))
    pages = list(reader.pages)
    n = len(pages)
    if n <= 1:
        _write_pdf(pages, out_path)
        return
    drop_n = max(1, int(round(n * max(0.0, min(drop_ratio, 0.95)))))
    keep_n = max(1, n - drop_n)
    keep_idx = sorted(rng.sample(range(n), keep_n))
    kept = [pages[i] for i in keep_idx]
    _write_pdf(kept, out_path)


def _noise_overlay_for_page(width: float, height: float, rng: random.Random) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.setFont("Helvetica", 8)
    for _ in range(14):
        x = rng.uniform(20, max(20, width - 140))
        y = rng.uniform(20, max(20, height - 20))
        token = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(10))
        c.drawString(x, y, f"noise-{token}")
    c.save()
    return buf.getvalue()


def _inject_noise(src: Path, out_path: Path, rng: random.Random, noise_page_ratio: float) -> None:
    reader = PdfReader(str(src))
    pages = list(reader.pages)
    n = len(pages)
    if n == 0:
        _write_pdf([], out_path)
        return
    touched = max(1, int(round(n * max(0.0, min(noise_page_ratio, 1.0)))))
    idxs = set(rng.sample(range(n), touched))
    writer = PdfWriter()
    for i, page in enumerate(pages):
        if i in idxs:
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            overlay_pdf = PdfReader(io.BytesIO(_noise_overlay_for_page(w, h, rng)))
            page.merge_page(overlay_pdf.pages[0])
        writer.add_page(page)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        writer.write(f)


def _mix_packets(src_a: Path, src_b: Path, out_path: Path, rng: random.Random) -> None:
    a_pages = list(PdfReader(str(src_a)).pages)
    b_pages = list(PdfReader(str(src_b)).pages)
    if not a_pages:
        _write_pdf(b_pages, out_path)
        return
    if not b_pages:
        _write_pdf(a_pages, out_path)
        return
    rng.shuffle(a_pages)
    rng.shuffle(b_pages)
    out: list = []
    a_idx = 0
    b_idx = 0
    # Deterministically interleave chunks so mixed structure is stressed.
    while a_idx < len(a_pages) or b_idx < len(b_pages):
        a_take = 1 if a_idx < len(a_pages) else 0
        b_take = 1 if b_idx < len(b_pages) else 0
        if rng.random() < 0.35 and a_idx + 1 < len(a_pages):
            a_take += 1
        if rng.random() < 0.35 and b_idx + 1 < len(b_pages):
            b_take += 1
        for _ in range(a_take):
            if a_idx < len(a_pages):
                out.append(a_pages[a_idx])
                a_idx += 1
        for _ in range(b_take):
            if b_idx < len(b_pages):
                out.append(b_pages[b_idx])
                b_idx += 1
    _write_pdf(out, out_path)


def _required_buckets(checklist: dict) -> tuple[str, ...]:
    metrics = ((checklist.get("quality_gates") or {}).get("Q_USE_1_required_buckets_present") or {}).get("metrics", {})
    buckets = sorted([k for k, v in metrics.items() if isinstance(v, (int, float)) and v > 0])
    return tuple(buckets)


def _load_csv_date_stats(run_id: str) -> tuple[int, int, float]:
    csv_path = ROOT / "data" / "artifacts" / run_id / "chronology.csv"
    if not csv_path.exists():
        return 0, 0, 0.0
    rows = 0
    dated = 0
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows += 1
            date_val = str(row.get("date") or row.get("Date") or "").strip()
            if DATE_RE.search(date_val):
                dated += 1
    ratio = round((dated / rows), 4) if rows else 0.0
    return rows, dated, ratio


def _build_snapshot(case_id: str, payload: dict, source_pdf: Path) -> Snapshot:
    run_id = str(payload.get("run_id") or "")
    qa_path = Path(payload["qa_litigation_checklist"])
    checklist = json.loads(qa_path.read_text(encoding="utf-8"))
    rows, dated, ratio = _load_csv_date_stats(run_id)
    timeline_coverage = float((checklist.get("metrics") or {}).get("timeline_citation_coverage") or 0.0)
    timeline_rows = int((checklist.get("metrics") or {}).get("timeline_rows") or 0)
    hard_codes = tuple(sorted(str(x.get("code")) for x in (checklist.get("hard_failures") or []) if x.get("code")))
    return Snapshot(
        case_id=case_id,
        run_id=run_id,
        source_pdf=str(source_pdf),
        source_pages=_page_count(source_pdf),
        qa_pass=bool(payload.get("qa_pass")),
        legal_pass=bool(payload.get("legal_pass")),
        overall_pass=bool(payload.get("overall_pass")),
        projection_entry_count=int(payload.get("projection_entry_count") or 0),
        gaps_count=int(payload.get("gaps_count") or 0),
        timeline_rows=timeline_rows,
        timeline_citation_coverage=timeline_coverage,
        required_buckets_present=_required_buckets(checklist),
        hard_failure_codes=hard_codes,
        csv_rows=rows,
        csv_dated_rows=dated,
        csv_date_parse_ratio=ratio,
    )


def _compare_invariants(base: Snapshot, pert: Snapshot, *, perturbation: str) -> dict:
    page_ratio = (pert.source_pages / base.source_pages) if base.source_pages else 0.0
    entry_ratio = (pert.projection_entry_count / base.projection_entry_count) if base.projection_entry_count else 0.0
    bucket_overlap = (
        len(set(base.required_buckets_present).intersection(set(pert.required_buckets_present)))
        / len(set(base.required_buckets_present))
        if base.required_buckets_present
        else 1.0
    )
    checks: dict[str, bool] = {}
    checks["citation_anchor_floor"] = pert.timeline_citation_coverage >= 0.85
    checks["hard_failures_not_introduced"] = (
        len(pert.hard_failure_codes) <= len(base.hard_failure_codes) or page_ratio < 0.7
    )
    if base.csv_rows == 0 or pert.csv_rows == 0 or base.csv_date_parse_ratio < 0.2:
        # If baseline has no usable date signal, do not fail perturbations for low date parse.
        checks["date_parse_floor"] = True
    else:
        checks["date_parse_floor"] = pert.csv_date_parse_ratio >= max(0.35, base.csv_date_parse_ratio * 0.6)
    checks["required_bucket_retention"] = bucket_overlap >= 0.5
    if perturbation == "mixed_structure":
        # Mixed packets are adversarial-by-design; enforce citation/date/bucket integrity, not pass parity.
        checks["qa_does_not_flip_without_large_page_loss"] = True
        checks["legal_does_not_flip_without_large_page_loss"] = True
    else:
        checks["qa_does_not_flip_without_large_page_loss"] = (not base.qa_pass or pert.qa_pass or page_ratio < 0.65)
        checks["legal_does_not_flip_without_large_page_loss"] = (not base.legal_pass or pert.legal_pass or page_ratio < 0.65)
    # Only enforce event-volume stability when the baseline has enough clinical signal.
    if base.projection_entry_count >= 6:
        if perturbation == "drop_pages":
            checks["event_volume_within_expected_drop_band"] = entry_ratio >= max(0.2, page_ratio * 0.35)
        else:
            checks["event_volume_within_expected_drop_band"] = entry_ratio >= 0.45
    else:
        checks["event_volume_within_expected_drop_band"] = True
    material_change = not all(checks.values())
    return {
        "material_change": material_change,
        "checks": checks,
        "metrics": {
            "page_ratio": round(page_ratio, 4),
            "entry_ratio": round(entry_ratio, 4),
            "bucket_overlap": round(bucket_overlap, 4),
            "base_entry_count": base.projection_entry_count,
            "pert_entry_count": pert.projection_entry_count,
            "base_citation_coverage": base.timeline_citation_coverage,
            "pert_citation_coverage": pert.timeline_citation_coverage,
            "base_date_parse_ratio": base.csv_date_parse_ratio,
            "pert_date_parse_ratio": pert.csv_date_parse_ratio,
        },
    }


def _determinism_probe(input_pdf: Path, case_id: str, run_label: str) -> dict:
    first = run_case(input_pdf, f"{case_id}_det_a", run_label=f"{run_label}_det_a")
    second = run_case(input_pdf, f"{case_id}_det_b", run_label=f"{run_label}_det_b")
    a = {
        "qa_pass": bool(first.get("qa_pass")),
        "legal_pass": bool(first.get("legal_pass")),
        "projection_entry_count": int(first.get("projection_entry_count") or 0),
        "gaps_count": int(first.get("gaps_count") or 0),
    }
    b = {
        "qa_pass": bool(second.get("qa_pass")),
        "legal_pass": bool(second.get("legal_pass")),
        "projection_entry_count": int(second.get("projection_entry_count") or 0),
        "gaps_count": int(second.get("gaps_count") or 0),
    }
    return {
        "stable": a == b,
        "first": a,
        "second": b,
        "hash_first": _stable_hash(a),
        "hash_second": _stable_hash(b),
    }


def evaluate(
    input_dir: Path,
    out_json: Path,
    *,
    sample_size: int,
    seed: int,
    drop_ratio: float,
    noise_ratio: float,
    determinism_probe: bool,
) -> dict:
    rng = random.Random(seed)
    seeds = _discover_seed_pdfs(input_dir, sample_size, seed)
    tmp_root = ROOT / "tmp" / "robustness"
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    material_changes = 0
    determinism_failures = 0

    for i, src in enumerate(seeds, start=1):
        case_base = f"robust_base_{i:03d}"
        base_payload = run_case(src, case_base, run_label=f"robust_base_{seed}_{i:03d}")
        base_snap = _build_snapshot(case_base, base_payload, src)

        if determinism_probe:
            det = _determinism_probe(src, case_base, f"robust_base_det_{seed}_{i:03d}")
            if not det["stable"]:
                determinism_failures += 1
        else:
            det = None

        perturbations: list[tuple[str, Path]] = []
        local = tmp_root / f"seed_{i:03d}"
        local.mkdir(parents=True, exist_ok=True)

        shuffled = local / "shuffle.pdf"
        _shuffle_pages(src, shuffled, rng)
        perturbations.append(("shuffle_order", shuffled))

        dropped = local / "drop_pages.pdf"
        _drop_random_pages(src, dropped, rng, drop_ratio)
        perturbations.append(("drop_pages", dropped))

        noisy = local / "noise.pdf"
        _inject_noise(src, noisy, rng, noise_ratio)
        perturbations.append(("inject_noise", noisy))

        if len(seeds) > 1:
            other = seeds[(i % len(seeds))]
            mixed = local / "mixed.pdf"
            _mix_packets(src, other, mixed, rng)
            perturbations.append(("mixed_structure", mixed))

        for p_name, p_path in perturbations:
            pert_case = f"robust_{p_name}_{i:03d}"
            pert_payload = run_case(p_path, pert_case, run_label=f"robust_{p_name}_{seed}_{i:03d}")
            pert_snap = _build_snapshot(pert_case, pert_payload, p_path)
            cmp = _compare_invariants(base_snap, pert_snap, perturbation=p_name.replace("inject_noise", "noise"))
            if cmp["material_change"]:
                material_changes += 1
            rows.append(
                {
                    "seed_pdf": str(src),
                    "perturbation": p_name,
                    "baseline": base_snap.__dict__,
                    "perturbed": pert_snap.__dict__,
                    "comparison": cmp,
                    "determinism_probe": det,
                }
            )

    total = len(rows)
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_dir),
        "sample_size": sample_size,
        "seed": seed,
        "drop_ratio": drop_ratio,
        "noise_ratio": noise_ratio,
        "total_comparisons": total,
        "material_changes": material_changes,
        "material_change_rate": round((material_changes / total), 4) if total else 0.0,
        "determinism_probe_enabled": determinism_probe,
        "determinism_failures": determinism_failures,
        "overall_invariant_stable": material_changes == 0 and determinism_failures == 0,
        "results": rows,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Adversarial robustness eval for chronology invariants.")
    parser.add_argument("--input-dir", default=str(ROOT / "PacketIntake"))
    parser.add_argument("--output-json", default=str(ROOT / "readiness" / "robustness_invariant_report.json"))
    parser.add_argument("--sample-size", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260220)
    parser.add_argument("--drop-ratio", type=float, default=0.25)
    parser.add_argument("--noise-ratio", type=float, default=0.2)
    parser.add_argument("--skip-determinism-probe", action="store_true")
    args = parser.parse_args()

    summary = evaluate(
        Path(args.input_dir),
        Path(args.output_json),
        sample_size=max(1, int(args.sample_size)),
        seed=int(args.seed),
        drop_ratio=float(args.drop_ratio),
        noise_ratio=float(args.noise_ratio),
        determinism_probe=not bool(args.skip_determinism_probe),
    )
    print(
        json.dumps(
            {
                "overall_invariant_stable": summary["overall_invariant_stable"],
                "total_comparisons": summary["total_comparisons"],
                "material_changes": summary["material_changes"],
                "material_change_rate": summary["material_change_rate"],
                "determinism_failures": summary["determinism_failures"],
            },
            indent=2,
        )
    )
    return 0 if summary["overall_invariant_stable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
