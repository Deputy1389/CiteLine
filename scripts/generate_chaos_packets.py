from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "data" / "synthea" / "packets"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "synthea" / "chaos"

TIERS = ("mild", "moderate", "severe")


def _seed_for(source_name: str, tier: str, seed: int) -> int:
    digest = hashlib.sha256(f"{source_name}|{tier}|{seed}".encode("utf-8")).hexdigest()[:16]
    return int(digest, 16)


def _plan_indices(page_count: int, tier: str, rng: random.Random) -> list[int]:
    indices = list(range(page_count))
    if page_count == 0:
        return indices
    if tier == "mild":
        if page_count >= 4:
            i = rng.randrange(0, page_count - 1)
            indices[i], indices[i + 1] = indices[i + 1], indices[i]
        dup_count = max(1, page_count // 20)
        for _ in range(dup_count):
            indices.insert(rng.randrange(0, len(indices) + 1), rng.randrange(0, page_count))
    elif tier == "moderate":
        swap_count = max(2, page_count // 10)
        for _ in range(swap_count):
            i = rng.randrange(0, page_count)
            j = rng.randrange(0, page_count)
            indices[i], indices[j] = indices[j], indices[i]
        drop_count = max(1, page_count // 25)
        for _ in range(drop_count):
            if len(indices) <= 1:
                break
            indices.pop(rng.randrange(0, len(indices)))
        dup_count = max(2, page_count // 15)
        for _ in range(dup_count):
            indices.insert(rng.randrange(0, len(indices) + 1), rng.randrange(0, page_count))
    else:  # severe
        rng.shuffle(indices)
        drop_count = max(2, page_count // 20)
        for _ in range(drop_count):
            if len(indices) <= 2:
                break
            indices.pop(rng.randrange(0, len(indices)))
        dup_count = max(3, page_count // 10)
        for _ in range(dup_count):
            indices.insert(rng.randrange(0, len(indices) + 1), rng.randrange(0, page_count))
    return indices


def _stamp_noise(page: fitz.Page, tier: str, page_idx: int, rng: random.Random) -> list[str]:
    mutations: list[str] = []
    header = f"Scanned Copy // {tier.upper()} // segment {rng.randint(100, 999)}"
    page.insert_text((36, 22), header, fontsize=8, color=(0.35, 0.35, 0.35))
    mutations.append("header_noise")

    footer_artifacts = [
        f"Printed Page {rng.randint(40, 900)}",
        f"s {rng.randint(1, 250)}-{rng.randint(251, 500)}",
        f"pdf_page_{rng.randint(1, 999)}",
    ]
    footer = rng.choice(footer_artifacts)
    page.insert_text((36, page.rect.height - 18), footer, fontsize=7, color=(0.4, 0.4, 0.4))
    mutations.append("footer_artifact")

    if tier in {"moderate", "severe"} and page_idx % 3 == 0:
        page.insert_text((300, 30), "04/10  98/68  12/??", fontsize=7, color=(0.45, 0.45, 0.45))
        mutations.append("date_fragment_noise")

    if tier == "severe" and page_idx % 4 == 0:
        page.insert_text((48, 52), "Patient Name: UNKNOWN ???", fontsize=8, color=(0.45, 0.1, 0.1))
        mutations.append("ambiguous_patient_header")

    if tier == "severe" and page_idx % 5 == 0:
        page.insert_text((48, 68), "Review of Systems: copied from prior note", fontsize=7, color=(0.45, 0.2, 0.2))
        mutations.append("ros_bleed_noise")

    return mutations


def mutate_pdf(source_pdf: Path, out_pdf: Path, tier: str, seed: int) -> dict:
    src_doc = fitz.open(str(source_pdf))
    source_page_count = int(src_doc.page_count)
    rng = random.Random(_seed_for(source_pdf.name, tier, seed))
    plan = _plan_indices(source_page_count, tier, rng)

    out_doc = fitz.open()
    mutation_counts: dict[str, int] = {}
    for idx, src_page_number in enumerate(plan):
        out_doc.insert_pdf(src_doc, from_page=src_page_number, to_page=src_page_number)
        page = out_doc[-1]
        applied = _stamp_noise(page, tier, idx, rng)
        for m in applied:
            mutation_counts[m] = mutation_counts.get(m, 0) + 1

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_doc.save(str(out_pdf))
    out_doc.close()
    src_doc.close()

    return {
        "source_pdf": str(source_pdf),
        "output_pdf": str(out_pdf),
        "tier": tier,
        "seed": _seed_for(source_pdf.name, tier, seed),
        "source_pages": source_page_count,
        "output_pages": len(plan),
        "plan_length": len(plan),
        "mutation_counts": mutation_counts,
    }


def generate_chaos_packets(
    *,
    source_dir: Path,
    output_dir: Path,
    max_sources: int,
    seed: int,
) -> dict:
    pdfs = sorted([p for p in source_dir.glob("*.pdf") if p.is_file()])
    if not pdfs:
        raise FileNotFoundError(f"No source PDFs found in {source_dir}")

    rng = random.Random(seed)
    if max_sources > 0 and len(pdfs) > max_sources:
        selected_idx = sorted(rng.sample(range(len(pdfs)), max_sources))
        selected = [pdfs[i] for i in selected_idx]
    else:
        selected = pdfs

    rows: list[dict] = []
    for src in selected:
        for tier in TIERS:
            tier_dir = output_dir / tier
            out_pdf = tier_dir / f"{src.stem}_chaos_{tier}.pdf"
            rows.append(mutate_pdf(src, out_pdf, tier, seed))

    summary = {
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "seed": seed,
        "selected_sources": len(selected),
        "generated_packets": len(rows),
        "tiers": list(TIERS),
        "rows": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic chaotic Synthea packets.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-sources", type=int, default=20, help="0 means all source packets.")
    parser.add_argument("--seed", type=int, default=1337)
    args = parser.parse_args()

    summary = generate_chaos_packets(
        source_dir=Path(args.source_dir),
        output_dir=Path(args.output_dir),
        max_sources=args.max_sources,
        seed=args.seed,
    )
    print(
        json.dumps(
            {
                "selected_sources": summary["selected_sources"],
                "generated_packets": summary["generated_packets"],
                "output_dir": summary["output_dir"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
