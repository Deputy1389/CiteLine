from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from apps.worker.lib.noise_filter import is_noise_span


SECTION_HEADERS = (
    "Medical Chronology Analysis",
    "Chronological Medical Timeline",
    "Top 10 Case-Driving Events",
    "Appendix A:",
    "Appendix B:",
    "Appendix C",
)
ROW_RE = re.compile(r"(?im)^((?:\d{4}-\d{2}-\d{2}|Undated))\s*\|\s*Encounter:\s*(.+)$")
FACT_TOKEN_PATTERNS = [
    re.compile(r"\bchief complaint\b", re.IGNORECASE),
    re.compile(r"\bhpi\b|\bhistory of present illness\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*/\s*10\b", re.IGNORECASE),  # pain
    re.compile(r"\b\d+\s*(?:deg|degree|degrees)\b", re.IGNORECASE),  # ROM
    re.compile(r"\b[0-5](?:\.\d+)?\s*/\s*5\b", re.IGNORECASE),  # strength
    re.compile(r"\b(?:bp|blood pressure)\s*[:=]?\s*\d{2,3}\s*/\s*\d{2,3}\b", re.IGNORECASE),  # vitals
    re.compile(r"\b(?:hydrocodone|oxycodone|lidocaine|depo-?medrol|toradol|ketorolac|ibuprofen|acetaminophen)\b.*\b\d+(?:\.\d+)?\s*(?:mg|mcg|ml)\b", re.IGNORECASE),
    re.compile(r"\b(?:c\d-\d|l\d-\d|radiculopathy|disc|protrusion|stenosis|strain|sprain)\b", re.IGNORECASE),
    re.compile(r"\b(?:assessment|impression|plan)\b", re.IGNORECASE),
    re.compile(r"\b(?:procedure|fluoroscopy|injection)\b", re.IGNORECASE),
]
BUCKET_SIGNALS = {
    "ED": re.compile(r"\b(triage|hpi|emergency|ed visit|chief complaint)\b", re.IGNORECASE),
    "MRI": re.compile(r"\bmri\b.*\b(impression|findings|c\d-\d|l\d-\d)\b|\bimpression\b.*\bmri\b", re.IGNORECASE),
    "ORTHO": re.compile(r"\b(ortho|orthopedic|orthopaedic)\b.*\b(assessment|plan|impression)\b", re.IGNORECASE),
    "PROCEDURE": re.compile(r"\b(depo-?medrol|lidocaine|fluoroscopy|interlaminar|transforaminal|epidural)\b", re.IGNORECASE),
}


@dataclass
class _TimelineRow:
    date_text: str
    event_type: str
    facts: list[str]
    citation: str


def _extract_timeline_slice(report_text: str) -> str:
    low = report_text.lower()
    start = low.find("chronological medical timeline")
    if start < 0:
        return report_text
    end = low.find("top 10 case-driving events", start + 1)
    if end < 0:
        end = len(report_text)
    return report_text[start:end]


def _parse_rows(timeline_text: str) -> list[_TimelineRow]:
    rows: list[_TimelineRow] = []
    cur: _TimelineRow | None = None
    for raw in timeline_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = ROW_RE.match(line)
        if m:
            if cur:
                rows.append(cur)
            cur = _TimelineRow(date_text=m.group(1).strip(), event_type=m.group(2).strip(), facts=[], citation="")
            continue
        if cur is None:
            continue
        if line.lower().startswith("citation(s):"):
            cur.citation = line
        elif not line.lower().startswith("facility/clinician:"):
            cur.facts.append(line)
    if cur:
        rows.append(cur)
    return rows


def _rows_from_projection_entries(entries: list[Any]) -> list[_TimelineRow]:
    rows: list[_TimelineRow] = []
    for e in entries or []:
        facts = [str(f or "") for f in (getattr(e, "facts", []) or []) if str(f or "").strip()]
        if not facts:
            continue
        facts_text = " ".join(facts)
        citation = str(getattr(e, "citation_display", "") or "").strip()
        if not citation:
            continue
        if is_noise_span(facts_text):
            continue
        if _fact_category_count(facts_text) < 2:
            continue
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", str(getattr(e, "date_display", "") or ""))
        dt = m.group(1) if m else "Undated"
        rows.append(
            _TimelineRow(
                date_text=dt,
                event_type=str(getattr(e, "event_type_display", "") or ""),
                facts=facts,
                citation=f"Citation(s): {citation}",
            )
        )
    return rows


def _merge_rows(parsed_rows: list[_TimelineRow], projection_rows: list[_TimelineRow]) -> list[_TimelineRow]:
    merged: list[_TimelineRow] = []
    seen: set[tuple[str, str, str]] = set()
    for row in parsed_rows + projection_rows:
        key = (row.date_text.strip().lower(), row.event_type.strip().lower(), row.citation.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _fact_category_count(text: str) -> int:
    return sum(1 for rex in FACT_TOKEN_PATTERNS if rex.search(text or ""))


def _source_buckets(page_text_by_number: dict[int, str] | None) -> set[str]:
    present: set[str] = set()
    for txt in (page_text_by_number or {}).values():
        if not txt:
            continue
        for b, rex in BUCKET_SIGNALS.items():
            if rex.search(txt):
                present.add(b)
    return present


def _timeline_buckets(rows: list[_TimelineRow]) -> set[str]:
    present: set[str] = set()
    for row in rows:
        blob = f"{row.event_type} {' '.join(row.facts)}".lower()
        if re.search(r"\b(ed|emergency|chief complaint|triage)\b", blob):
            present.add("ED")
        if re.search(r"\b(mri|impression|imaging)\b", blob):
            present.add("MRI")
        if re.search(r"\b(ortho|orthopedic|orthopaedic)\b", blob):
            present.add("ORTHO")
        if re.search(r"\b(procedure|injection|fluoroscopy|depo-medrol|lidocaine)\b", blob):
            present.add("PROCEDURE")
    return present


def _projection_buckets(entries: list[Any]) -> set[str]:
    present: set[str] = set()
    for e in entries or []:
        blob = (
            f"{str(getattr(e, 'event_type_display', '') or '')} "
            f"{' '.join(str(f or '') for f in (getattr(e, 'facts', []) or []))}"
        ).lower()
        if re.search(r"\b(ed|emergency|chief complaint|triage)\b", blob):
            present.add("ED")
        if re.search(r"\b(mri|impression|imaging)\b", blob):
            present.add("MRI")
        if re.search(r"\b(ortho|orthopedic|orthopaedic)\b", blob):
            present.add("ORTHO")
        if re.search(r"\b(procedure|injection|fluoroscopy|depo-medrol|lidocaine|epidural)\b", blob):
            present.add("PROCEDURE")
    return present


def _is_milestone_row(row: _TimelineRow) -> bool:
    blob = f"{row.event_type} {' '.join(row.facts)}".lower()
    return bool(
        re.search(
            r"\b(ed|emergency|mri|imaging|orthopedic|ortho|procedure|injection|fluoroscopy|admission|discharge)\b",
            blob,
        )
    )


def build_attorney_readiness_report(report_text: str, ctx: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    hard_fail = False
    penalties = 0.0

    missing_sections = [h for h in SECTION_HEADERS if h.lower() not in report_text.lower()]
    if missing_sections:
        hard_fail = True
        failures.append(
            {
                "code": "AR_MISSING_REQUIRED_SECTIONS",
                "severity": "hard",
                "message": "Required litigation sections missing.",
                "examples": missing_sections[:5],
            }
        )

    timeline_text = _extract_timeline_slice(report_text)
    rows = _parse_rows(timeline_text)
    projection_rows = _rows_from_projection_entries(list(ctx.get("projection_entries", []) or []))
    if len(rows) < max(2, min(5, len(projection_rows) // 2)):
        rows = _merge_rows(rows, projection_rows)
    row_count = len(rows)
    if row_count == 0:
        hard_fail = True
        failures.append(
            {
                "code": "AR_EMPTY_TIMELINE",
                "severity": "hard",
                "message": "No timeline rows rendered.",
                "examples": [],
            }
        )

    uncited_rows = [r for r in rows if not (r.citation or "").strip()]
    uncited_ratio = (len(uncited_rows) / row_count) if row_count else 1.0
    if uncited_ratio > 0.05:
        hard_fail = True
        failures.append(
            {
                "code": "AR_UNCITED_FACT_ROWS",
                "severity": "hard",
                "message": f"Too many uncited timeline rows: {uncited_ratio:.3f}",
                "examples": [f"{r.date_text} | {r.event_type}" for r in uncited_rows[:3]],
            }
        )

    dense_rows = 0
    for r in rows:
        cats = _fact_category_count(" ".join(r.facts))
        if cats >= 2 or (_is_milestone_row(r) and cats >= 1):
            dense_rows += 1
    fact_density_ratio = (dense_rows / row_count) if row_count else 0.0
    if fact_density_ratio < 0.60:
        hard_fail = True
        failures.append(
            {
                "code": "AR_FACT_DENSITY_LOW",
                "severity": "hard",
                "message": f"Fact-dense row ratio below threshold: {fact_density_ratio:.3f}",
                "examples": [(" ".join(r.facts)[:140]) for r in rows[:3]],
            }
        )
    penalties += min(30.0, max(0.0, (0.60 - fact_density_ratio)) * 30.0)

    src_buckets = _source_buckets(ctx.get("page_text_by_number") or {})
    timeline_buckets = _timeline_buckets(rows) | _projection_buckets(list(ctx.get("projection_entries", []) or []))
    missing_buckets = sorted(src_buckets - timeline_buckets)
    if missing_buckets:
        hard_fail = True
        failures.append(
            {
                "code": "AR_REQUIRED_BUCKETS_MISSING",
                "severity": "hard",
                "message": "Milestone buckets present in source but missing in timeline.",
                "examples": missing_buckets[:5],
            }
        )

    score = max(0, min(100, int(round(100 - penalties))))
    if hard_fail:
        score = min(score, 60)
    pass_flag = (not hard_fail) and score >= 90
    return {
        "attorney_ready_pass": pass_flag,
        "attorney_ready_score_0_100": score,
        "failures": failures,
        "metrics": {
            "timeline_row_count": row_count,
            "uncited_ratio": round(uncited_ratio, 3),
            "fact_density_ratio": round(fact_density_ratio, 3),
            "missing_buckets": missing_buckets,
            "missing_sections": missing_sections,
        },
    }
