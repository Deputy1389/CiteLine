"""
CLI tool: Export chronology from a completed run.

Usage:
    python -m apps.worker.tools.export_chronology --run <RUN_ID> --out <DIR>

Loads the saved evidence_graph.json for the given run, then generates
chronology.pdf, chronology.csv, chronology.docx, and chronology.json
in the specified output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Export chronology files from a completed CiteLine run.",
    )
    parser.add_argument("--run", required=True, help="Run ID to export from")
    parser.add_argument("--out", required=True, help="Output directory for export files")
    parser.add_argument(
        "--data-dir", default="data",
        help="Data directory where run artifacts are stored (default: data)",
    )
    parser.add_argument(
        "--title", default="Chronology Export",
        help="Matter title for the export header (default: 'Chronology Export')",
    )
    args = parser.parse_args()

    run_id = args.run
    out_dir = Path(args.out)
    data_dir = Path(args.data_dir)
    matter_title = args.title

    # Find evidence_graph.json
    eg_path = data_dir / "runs" / run_id / "evidence_graph.json"
    if not eg_path.exists():
        print(f"ERROR: evidence_graph.json not found at {eg_path}", file=sys.stderr)
        print(f"Make sure run '{run_id}' has completed processing.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading evidence graph from {eg_path}...")
    with open(eg_path, "r", encoding="utf-8") as f:
        eg_data = json.load(f)

    # Parse into domain models
    from packages.shared.models import EvidenceGraph
    evidence_graph = EvidenceGraph.model_validate(eg_data)

    events = evidence_graph.events
    gaps = evidence_graph.gaps
    providers = evidence_graph.providers

    if not events:
        print("WARNING: No events found in this run.", file=sys.stderr)

    # Build page_map from documents + pages
    page_map: dict[int, tuple[str, int]] = {}
    doc_filenames: dict[str, str] = {}
    for doc in evidence_graph.documents:
        doc_filenames[doc.source_document_id] = doc.detected_title or doc.source_document_id

    page_counts: dict[str, int] = {}
    for page in sorted(evidence_graph.pages, key=lambda p: p.page_number):
        sid = page.source_document_id
        page_counts[sid] = page_counts.get(sid, 0) + 1
        local_num = page_counts[sid]
        filename = doc_filenames.get(sid, sid)
        page_map[page.page_number] = (filename, local_num)

    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)

    # Import export generators
    from apps.worker.steps.step12_export import generate_pdf, generate_csv, generate_docx

    # Generate PDF
    print("Generating chronology.pdf...")
    pdf_bytes = generate_pdf(run_id, matter_title, events, gaps, providers, page_map)
    (out_dir / "chronology.pdf").write_bytes(pdf_bytes)

    # Generate CSV
    print("Generating chronology.csv...")
    csv_bytes = generate_csv(events, providers, page_map)
    (out_dir / "chronology.csv").write_bytes(csv_bytes)

    # Generate DOCX
    print("Generating chronology.docx...")
    docx_bytes = generate_docx(run_id, matter_title, events, gaps, providers, page_map)
    (out_dir / "chronology.docx").write_bytes(docx_bytes)

    # Generate JSON (ChronologyEntry format)
    print("Generating chronology.json...")
    entries = []
    for evt in events:
        # Build sources list
        sources = []
        for cid in evt.citation_ids:
            cit = next((c for c in evidence_graph.citations if c.citation_id == cid), None)
            if cit:
                fname = doc_filenames.get(cit.source_document_id, cit.source_document_id)
                sources.append({
                    "document_name": fname,
                    "document_id": cit.source_document_id,
                    "page_number": cit.page_number,
                    "bbox": cit.bbox.model_dump() if cit.bbox else None,
                    "snippet": cit.snippet,
                })
            else:
                sources.append({
                    "document_name": "Unknown",
                    "page_number": None,
                    "bbox": None,
                    "snippet": None,
                })

        # Determine confidence label
        conf = evt.confidence
        if conf >= 80:
            conf_label = "HIGH"
        elif conf >= 50:
            conf_label = "MED"
        else:
            conf_label = "LOW"

        # Build flags
        flags = list(evt.flags)
        if evt.date is None or evt.date.value is None:
            if "MISSING_DATE" not in flags:
                flags.append("MISSING_DATE")
        if not sources or all(s.get("page_number") is None for s in sources):
            if "MISSING_SOURCE" not in flags:
                flags.append("MISSING_SOURCE")
        if flags and "NEEDS_REVIEW" not in flags:
            flags.append("NEEDS_REVIEW")

        # Provider name
        provider_name = None
        if evt.provider_id:
            prov = next((p for p in providers if p.provider_id == evt.provider_id), None)
            if prov:
                provider_name = prov.normalized_name

        entries.append({
            "event_id": evt.event_id,
            "event_date": str(evt.date.sort_date()) if evt.date else None,
            "event_date_source": evt.date.source.value if evt.date else "NONE",
            "event_type": evt.event_type.value,
            "provider_name": provider_name,
            "description": "; ".join(f.text for f in evt.facts[:6]),
            "sources": sources,
            "confidence": conf_label,
            "flags": flags,
        })

    json_bytes = json.dumps(entries, indent=2, default=str).encode("utf-8")
    (out_dir / "chronology.json").write_bytes(json_bytes)

    # Summary
    print(f"\n✓ Exported {len(events)} events to {out_dir}/")
    print(f"  - chronology.pdf  ({len(pdf_bytes):,} bytes)")
    print(f"  - chronology.csv  ({len(csv_bytes):,} bytes)")
    print(f"  - chronology.docx ({len(docx_bytes):,} bytes)")
    print(f"  - chronology.json ({len(json_bytes):,} bytes)")


if __name__ == "__main__":
    main()
