"""
Extraction quality evaluation harness.

Runs the extraction pipeline (steps 1-10) on each testdata PDF without needing
a live API or database. Prints a per-file scorecard and aggregate summary.

Usage:
    $env:PYTHONPATH="C:\CiteLine"
    python -m apps.worker.lib.eval_harness
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def collect_test_pdfs(test_dir: str = "testdata") -> list[Path]:
    """Find all PDF files in the testdata directory."""
    test_path = Path(test_dir)
    if not test_path.exists():
        print(f"Error: {test_dir} not found")
        sys.exit(1)
    pdfs = sorted(test_path.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {test_dir}")
        sys.exit(1)
    return pdfs


def run_extraction(pdf_path: Path) -> dict:
    """
    Run extraction pipeline steps on a single PDF, returning metrics.
    This replaces needing the full API/DB pipeline.
    """
    import uuid
    import fitz  # PyMuPDF

    from packages.shared.models import (
        Page,
        RunConfig,
        SourceDocument,
    )
    from apps.worker.steps.step01_page_split import split_pages
    from apps.worker.steps.step02_text_acquire import acquire_text
    from apps.worker.steps.step03_classify import classify_pages
    from apps.worker.steps.step04_segment import segment_documents
    from apps.worker.steps.step05_provider import detect_providers
    from apps.worker.steps.step06_dates import extract_dates_for_pages
    from apps.worker.steps.step07_events import (
        extract_billing_events,
        extract_clinical_events,
        extract_imaging_events,
        extract_pt_events,
    )
    from apps.worker.steps.step09_dedup import deduplicate_events
    from apps.worker.steps.step10_confidence import apply_confidence_scoring

    config = RunConfig()
    doc_id = uuid.uuid4().hex[:16]

    # Step 1: Page splitting
    try:
        pages, _ = split_pages(str(pdf_path), doc_id)
    except Exception as e:
        return {"error": str(e), "file": pdf_path.name}

    # Step 2: Text acquisition
    pages, _, _ = acquire_text(pages, str(pdf_path))

    # Step 3: Classification
    pages, _ = classify_pages(pages)

    # Step 4: Segmentation
    documents, _ = segment_documents(pages, doc_id)

    # Step 5: Provider detection
    providers, page_provider_map, _ = detect_providers(pages, documents)

    # Step 6: Date extraction
    dates = extract_dates_for_pages(pages)

    # Step 7: Event extraction (all types)
    all_events = []
    all_citations = []
    all_skipped = []

    clinical_events, clinical_cits, _, clinical_skipped = extract_clinical_events(
        pages, dates, providers, page_provider_map
    )
    all_events.extend(clinical_events)
    all_citations.extend(clinical_cits)
    all_skipped.extend(clinical_skipped)

    imaging_events, imaging_cits, _, imaging_skipped = extract_imaging_events(
        pages, dates, providers, page_provider_map
    )
    all_events.extend(imaging_events)
    all_citations.extend(imaging_cits)
    all_skipped.extend(imaging_skipped)

    pt_events, pt_cits, _, pt_skipped = extract_pt_events(
        pages, dates, providers, config, page_provider_map
    )
    all_events.extend(pt_events)
    all_citations.extend(pt_cits)
    all_skipped.extend(pt_skipped)

    billing_events, billing_cits, _, billing_skipped = extract_billing_events(
        pages, dates, providers, page_provider_map
    )
    all_events.extend(billing_events)
    all_citations.extend(billing_cits)
    all_skipped.extend(billing_skipped)

    # Step 9: Dedup
    all_events, _ = deduplicate_events(all_events)

    # Step 10: Confidence scoring
    all_events, _ = apply_confidence_scoring(all_events, config)

    # Collect metrics
    page_type_counts: dict[str, int] = {}
    for p in pages:
        pt = p.page_type.value if p.page_type else "other"
        page_type_counts[pt] = page_type_counts.get(pt, 0) + 1

    event_type_counts: dict[str, int] = {}
    for e in all_events:
        et = e.event_type.value
        event_type_counts[et] = event_type_counts.get(et, 0) + 1

    fact_kind_counts: dict[str, int] = {}
    for e in all_events:
        for f in e.facts:
            kind = f.kind.value if hasattr(f.kind, "value") else str(f.kind)
            fact_kind_counts[kind] = fact_kind_counts.get(kind, 0) + 1

    confidence_scores = [e.confidence for e in all_events]
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0

    return {
        "file": pdf_path.name,
        "pages": len(pages),
        "page_types": page_type_counts,
        "providers": len(providers),
        "provider_names": [p.detected_name_raw for p in providers],
        "events": len(all_events),
        "events_by_type": event_type_counts,
        "events_with_date": sum(1 for e in all_events if e.date),
        "events_dateless": sum(1 for e in all_events if not e.date),
        "facts_total": sum(len(e.facts) for e in all_events),
        "fact_kinds": fact_kind_counts,
        "citations": len(all_citations),
        "skipped": len(all_skipped),
        "avg_confidence": round(avg_confidence, 1),
        "low_confidence_count": sum(1 for s in confidence_scores if s < 40),
        "confidence_distribution": {
            "0-19": sum(1 for s in confidence_scores if s < 20),
            "20-39": sum(1 for s in confidence_scores if 20 <= s < 40),
            "40-59": sum(1 for s in confidence_scores if 40 <= s < 60),
            "60-79": sum(1 for s in confidence_scores if 60 <= s < 80),
            "80-100": sum(1 for s in confidence_scores if s >= 80),
        },
    }


def print_scorecard(result: dict) -> None:
    """Print a formatted scorecard for a single file."""
    print(f"\n{'='*60}")
    print(f"  {result['file']}")
    print(f"{'='*60}")

    if "error" in result:
        print(f"  ❌ ERROR: {result['error']}")
        return

    print(f"  Pages:      {result['pages']:>4}  | Types: {result['page_types']}")
    print(f"  Providers:  {result['providers']:>4}  | {', '.join(result['provider_names'][:3])}")
    print(f"  Events:     {result['events']:>4}  | By type: {result['events_by_type']}")
    print(f"  Facts:      {result['facts_total']:>4}  | Kinds: {result['fact_kinds']}")
    print(f"  Citations:  {result['citations']:>4}  | Skipped: {result['skipped']}")
    print(f"  Dates:      {result['events_with_date']:>4} with, {result['events_dateless']} without")
    print(f"  Confidence: avg={result['avg_confidence']:.0f}  | {result['confidence_distribution']}")

    # Quality flags
    flags = []
    if result["events"] == 0:
        flags.append("⚠️  ZERO EVENTS")
    if result["providers"] == 0:
        flags.append("⚠️  NO PROVIDERS")
    if result["events_dateless"] > result["events_with_date"]:
        flags.append("⚠️  MOSTLY DATELESS")
    if result["avg_confidence"] < 30:
        flags.append("⚠️  LOW CONFIDENCE")
    if result["facts_total"] == 0:
        flags.append("⚠️  NO FACTS")

    if flags:
        print(f"  FLAGS: {' | '.join(flags)}")


def print_summary(results: list[dict]) -> None:
    """Print aggregate summary."""
    valid = [r for r in results if "error" not in r]
    if not valid:
        print("\n  No valid results to summarize.")
        return

    print(f"\n{'='*60}")
    print(f"  AGGREGATE SUMMARY ({len(valid)} files)")
    print(f"{'='*60}")

    total_pages = sum(r["pages"] for r in valid)
    total_events = sum(r["events"] for r in valid)
    total_facts = sum(r["facts_total"] for r in valid)
    total_with_date = sum(r["events_with_date"] for r in valid)
    total_dateless = sum(r["events_dateless"] for r in valid)
    avg_conf = sum(r["avg_confidence"] for r in valid) / len(valid)

    print(f"  Total pages:        {total_pages}")
    print(f"  Total events:       {total_events}")
    print(f"  Total facts:        {total_facts}")
    print(f"  Events with date:   {total_with_date} ({total_with_date/(total_events or 1)*100:.0f}%)")
    print(f"  Events dateless:    {total_dateless}")
    print(f"  Avg confidence:     {avg_conf:.1f}")
    print(f"  Facts/event:        {total_facts/(total_events or 1):.1f}")

    # Files with issues
    zero_event_files = [r["file"] for r in valid if r["events"] == 0]
    low_conf_files = [r["file"] for r in valid if r["avg_confidence"] < 30]
    error_files = [r["file"] for r in results if "error" in r]

    if zero_event_files:
        print(f"\n  ⚠️  Zero-event files: {', '.join(zero_event_files)}")
    if low_conf_files:
        print(f"  ⚠️  Low-confidence files: {', '.join(low_conf_files)}")
    if error_files:
        print(f"  ❌ Error files: {', '.join(error_files)}")


def main():
    print(f"\n  CiteLine Extraction Quality Eval")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  {'─'*40}")

    pdfs = collect_test_pdfs()
    print(f"  Found {len(pdfs)} test PDFs\n")

    results = []
    for pdf in pdfs:
        print(f"  Processing: {pdf.name}...", end="", flush=True)
        try:
            result = run_extraction(pdf)
            results.append(result)
            if "error" in result:
                print(f" ❌")
            else:
                print(f" ✓ ({result['events']} events, {result['facts_total']} facts)")
        except Exception as e:
            print(f" ❌ {e}")
            results.append({"file": pdf.name, "error": str(e)})

    # Print scorecards
    for result in results:
        print_scorecard(result)

    # Print summary
    print_summary(results)

    # Save JSON results
    output_path = Path("testdata") / "eval_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
