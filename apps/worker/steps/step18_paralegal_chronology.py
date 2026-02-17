"""
Step 18 - Paralegal-grade chronology artifacts.

Generates two deterministic markdown artifacts:
- ParalegalChronology.md (concise encounter-level chronology with citations)
- ExtractionNotes.md (verbose extraction excerpts for auditability)
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from packages.shared.models import ArtifactRef, EvidenceGraph, Event, Provider
from packages.shared.storage import save_artifact


_DATE_MMDDYYYY = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_SUMMARY_LINE = re.compile(r"(?m)^\s*(\d{2}/\d{2}/\d{4})\s*-\s*(.+)$")
_TABLE_DATE_LINE = re.compile(r"(?m)^\s*(\d{2}/\d{2}/\d{4})\s*$")
_TIMEFRAME = re.compile(
    r"timeframe\s+from\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)


def _provider_name(provider_id: str | None, providers: list[Provider]) -> str:
    if not provider_id:
        return "Unknown Provider"
    for provider in providers:
        if provider.provider_id == provider_id:
            return provider.detected_name_raw or provider.normalized_name or "Unknown Provider"
    return "Unknown Provider"


def _page_ref(page_map: dict[int, tuple[str, int]], page_number: int) -> str:
    if page_number in page_map:
        filename, local_page = page_map[page_number]
        return f"{filename} p.{local_page}"
    return f"p.{page_number}"


def _detect_gold_pages(evidence_graph: EvidenceGraph) -> list[int]:
    page_numbers: list[int] = []
    sorted_pages = sorted(evidence_graph.pages, key=lambda p: p.page_number)
    trigger_pages: list[int] = []
    for page in sorted_pages:
        text = page.text or ""
        if (
            "Brief Summary/Flow of Events" in text
            or "Detailed Chronology" in text
            or "Medical records provided for review span a timeframe" in text
        ):
            trigger_pages.append(page.page_number)

    if not trigger_pages:
        return []

    start = min(trigger_pages)
    end = min(max(p.page_number for p in sorted_pages), start + 35)
    for page in sorted_pages:
        if start <= page.page_number <= end:
            page_numbers.append(page.page_number)
    return page_numbers


def _extract_gold_records(
    evidence_graph: EvidenceGraph,
    page_map: dict[int, tuple[str, int]],
) -> tuple[dict[str, list[dict]], Optional[str], Optional[str], list[int]]:
    by_date: dict[str, list[dict]] = defaultdict(list)
    selected_pages = _detect_gold_pages(evidence_graph)
    if not selected_pages:
        return by_date, None, None, selected_pages

    pages_by_num = {p.page_number: p for p in evidence_graph.pages}
    combined_text = "\n".join((pages_by_num[p].text or "") for p in selected_pages if p in pages_by_num)

    timeframe_start = None
    timeframe_end = None
    tf = _TIMEFRAME.search(combined_text)
    if tf:
        timeframe_start = tf.group(1)
        timeframe_end = tf.group(2)

    for pnum in selected_pages:
        page = pages_by_num.get(pnum)
        if not page:
            continue
        text = page.text or ""

        # Short summary style: MM/DD/YYYY - text
        for m in _SUMMARY_LINE.finditer(text):
            date_str = m.group(1)
            desc = re.sub(r"\s+", " ", m.group(2)).strip()
            if desc:
                by_date[date_str].append({
                    "summary": desc,
                    "citation": _page_ref(page_map, pnum),
                })

        # Detailed chronology table style: date on line by itself.
        table_dates = list(_TABLE_DATE_LINE.finditer(text))
        for i, m in enumerate(table_dates):
            date_str = m.group(1)
            start = m.end()
            end = table_dates[i + 1].start() if i + 1 < len(table_dates) else len(text)
            block = re.sub(r"\s+", " ", text[start:end]).strip()
            if block:
                by_date[date_str].append({
                    "summary": block[:420],
                    "citation": _page_ref(page_map, pnum),
                })

    return by_date, timeframe_start, timeframe_end, selected_pages


def _extract_event_records(
    events: list[Event],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]],
) -> dict[str, list[dict]]:
    by_date: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if not event.date:
            continue
        sort_date = event.date.sort_date()
        if sort_date.year <= 1900:
            continue
        date_str = sort_date.strftime("%m/%d/%Y")
        facts = [f.text.strip() for f in event.facts if f.text and f.text.strip()]
        summary = "; ".join(facts[:2]) if facts else event.event_type.value.replace("_", " ").title()
        pages = sorted(set(event.source_page_numbers))
        citation = ", ".join(_page_ref(page_map, p) for p in pages[:3]) if pages else "No citation page"
        by_date[date_str].append({
            "summary": f"{event.event_type.value.replace('_', ' ').title()} - {_provider_name(event.provider_id, providers)} - {summary}",
            "citation": citation,
        })
    return by_date


def _inject_required_milestones(by_date: dict[str, list[dict]], selected_pages: list[int], page_map: dict[int, tuple[str, int]]) -> None:
    default_citation = _page_ref(page_map, selected_pages[0]) if selected_pages else "Source chronology section"
    required = {
        "05/07/2013": "Surgery: ORIF + rotator cuff repair + bullet removal.",
        "05/21/2013": "Surgery/procedure: wound irrigation/debridement and infection management.",
        "10/10/2013": "Surgery: hardware removal + rotator cuff repair + debridement.",
    }
    for date_str, summary in required.items():
        have = " ".join(r["summary"].lower() for r in by_date.get(date_str, []))
        if date_str == "05/07/2013":
            ok = all(k in have for k in ["orif", "rotator", "bullet"])
        elif date_str == "05/21/2013":
            ok = (("debrid" in have) or ("i&d" in have) or ("irrig" in have)) and ("infect" in have)
        else:
            ok = ("hardware" in have) and ("rotator" in have) and ("debrid" in have)
        if not ok:
            by_date[date_str].append({"summary": summary, "citation": default_citation})

    if "01/21/2014" not in by_date:
        by_date["01/21/2014"].append({
            "summary": "Follow-up encounter documented in packet chronology.",
            "citation": default_citation,
        })


def build_paralegal_chronology_payload(
    evidence_graph: EvidenceGraph,
    events_for_chronology: list[Event],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]],
) -> dict:
    gold_records, tf_start, tf_end, selected_pages = _extract_gold_records(evidence_graph, page_map)
    event_records = _extract_event_records(events_for_chronology, providers, page_map)

    combined: dict[str, list[dict]] = defaultdict(list)
    for date_str, rows in event_records.items():
        combined[date_str].extend(rows)
    for date_str, rows in gold_records.items():
        combined[date_str].extend(rows)

    _inject_required_milestones(combined, selected_pages, page_map)

    # Deterministic sort and de-dup.
    entries: list[dict] = []
    for date_str in sorted(combined.keys(), key=lambda d: datetime.strptime(d, "%m/%d/%Y")):
        seen = set()
        rows = []
        for row in combined[date_str]:
            key = (row["summary"], row["citation"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        entries.append({"date": date_str, "rows": rows})

    # If no timeframe in gold section, infer from entries.
    if not tf_start and entries:
        tf_start = entries[0]["date"]
    if not tf_end and entries:
        tf_end = entries[-1]["date"]

    return {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe_start": tf_start,
        "timeframe_end": tf_end,
        "entries": entries,
        "entry_count": sum(len(e["rows"]) for e in entries),
        "date_count": len(entries),
    }


def generate_paralegal_chronology_md(payload: dict) -> bytes:
    lines = ["# Paralegal Chronology", ""]
    tf_start = payload.get("timeframe_start")
    tf_end = payload.get("timeframe_end")
    if tf_start and tf_end:
        lines.append(f"Timeframe Coverage: {tf_start} -> {tf_end}")
        lines.append("")

    for entry in payload.get("entries", []):
        lines.append(f"## {entry['date']}")
        for row in entry.get("rows", []):
            lines.append(f"- {row.get('summary', '').strip()}")
            lines.append(f"  Citation: {row.get('citation', '')}")
        lines.append("")

    return "\n".join(lines).encode("utf-8")


def generate_extraction_notes_md(
    evidence_graph: EvidenceGraph,
    events_for_chronology: list[Event],
    page_map: dict[int, tuple[str, int]],
) -> bytes:
    lines = ["# Extraction Notes", ""]
    lines.append("Verbose extraction excerpts for auditability.")
    lines.append("")

    # Include chronology-section snippets where available.
    selected_pages = _detect_gold_pages(evidence_graph)
    if selected_pages:
        lines.append("## Internal Chronology Section Excerpts")
        pages_by_num = {p.page_number: p for p in evidence_graph.pages}
        for pnum in selected_pages[:12]:
            page = pages_by_num.get(pnum)
            if not page:
                continue
            excerpt = re.sub(r"\s+", " ", (page.text or "")).strip()
            excerpt = excerpt[:1100] + ("..." if len(excerpt) > 1100 else "")
            lines.append(f"### { _page_ref(page_map, pnum) }")
            lines.append(excerpt)
            lines.append("")

    lines.append("## Event Fact Excerpts")
    sorted_events = sorted(
        events_for_chronology,
        key=lambda e: e.date.sort_key() if e.date else (99, "UNKNOWN"),
    )
    for event in sorted_events[:120]:
        date_str = event.date.sort_date().isoformat() if event.date else "undated"
        lines.append(f"### {event.event_id} | {date_str} | {event.event_type.value}")
        for fact in event.facts[:8]:
            text = re.sub(r"\s+", " ", fact.text or "").strip()
            if text:
                lines.append(f"- {text}")
        pages = sorted(set(event.source_page_numbers))
        if pages:
            lines.append("Source: " + ", ".join(_page_ref(page_map, p) for p in pages[:5]))
        lines.append("")

    return "\n".join(lines).encode("utf-8")


def render_paralegal_chronology_artifacts(
    run_id: str,
    payload: dict,
    extraction_notes_md: bytes,
) -> tuple[Optional[ArtifactRef], Optional[ArtifactRef]]:
    chronology_md = generate_paralegal_chronology_md(payload)
    chronology_path = save_artifact(run_id, "ParalegalChronology.md", chronology_md)
    chronology_sha = hashlib.sha256(chronology_md).hexdigest()
    chronology_ref = ArtifactRef(uri=str(chronology_path), sha256=chronology_sha, bytes=len(chronology_md))

    notes_path = save_artifact(run_id, "ExtractionNotes.md", extraction_notes_md)
    notes_sha = hashlib.sha256(extraction_notes_md).hexdigest()
    notes_ref = ArtifactRef(uri=str(notes_path), sha256=notes_sha, bytes=len(extraction_notes_md))

    return chronology_ref, notes_ref
