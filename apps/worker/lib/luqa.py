from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from apps.worker.lib.noise_filter import is_noise_span


META_PATTERNS = [
    r"identified from source",
    r"markers",
    r"extracted",
    r"encounter recorded",
    r"documentation suggests",
    r"consistent with.*encounter",
    r"outcome details limited",
    r"management actions are summarized",
]
META_RE = re.compile("|".join(f"(?:{p})" for p in META_PATTERNS), re.IGNORECASE)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
PLACEHOLDER_RE = re.compile(
    r"\b(limited detail|encounter recorded|clinical documentation(?:\s+only)?|documentation noted|continuity of care|not stated in records)\b",
    re.IGNORECASE,
)
ROW_RE = re.compile(r"(?im)^((?:\d{4}-\d{2}-\d{2}|Undated))\s*\|\s*Encounter:\s*(.+)$")
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
LEVEL_RE = re.compile(r"\b([cCtTlL]\d-\d)\b")
DOSAGE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*mg\b", re.IGNORECASE)
PAIN_RE = re.compile(r"\bpain(?:\s*(?:score|severity|level))?\s*[:=]?\s*\d{1,2}\s*/\s*10\b", re.IGNORECASE)
ROM_RE = re.compile(r"\b(?:rom|range of motion)\b|\b\d+\s*(?:deg|degree|degrees)\b", re.IGNORECASE)
STRENGTH_RE = re.compile(r"\bstrength\s*[:=]?\s*[0-5](?:\.\d+)?\s*/\s*5\b|\b[0-5]\s*/\s*5\b", re.IGNORECASE)
VITALS_RE = re.compile(r"\b(?:bp|blood pressure)\s*[:=]?\s*\d{2,3}\s*/\s*\d{2,3}\b|\bhr\s*\d+\b|\brr\s*\d+\b|\bspo2\s*\d+\b", re.IGNORECASE)
DX_RE = re.compile(
    r"\b(radiculopathy|herniation|disc|strain|sprain|stenosis|protrusion|fracture|tear|neuropathy)\b",
    re.IGNORECASE,
)
ENCOUNTER_RE = re.compile(r"\b(chief complaint|hpi|emergency|impression|assessment|plan|procedure|injection|fluoroscopy)\b", re.IGNORECASE)
MED_RE = re.compile(
    r"\b(hydrocodone|oxycodone|lidocaine|depo-?medrol|ibuprofen|acetaminophen|toradol|ketorolac|gabapentin|cyclobenzaprine|prednisone|naproxen)\b",
    re.IGNORECASE,
)
BUCKET_SIGNALS = {
    "ED": re.compile(r"\b(triage|hpi|emergency|ed visit|chief complaint)\b", re.IGNORECASE),
    "MRI": re.compile(r"\bmri\b.*\b(impression|findings|c\d-\d|l\d-\d)\b|\bimpression\b.*\bmri\b", re.IGNORECASE),
    "PT_EVAL": re.compile(r"\b(pt eval|physical therapy evaluation|soap)\b", re.IGNORECASE),
    "ORTHO": re.compile(r"\b(ortho|orthopedic|orthopaedic)\b.*\b(assessment|plan|impression)\b", re.IGNORECASE),
    "PROCEDURE": re.compile(r"\b(depo-?medrol|lidocaine|fluoroscopy|interlaminar|transforaminal|epidural)\b", re.IGNORECASE),
}
STOPWORDS = {
    "the",
    "and",
    "or",
    "a",
    "an",
    "to",
    "of",
    "in",
    "for",
    "with",
    "on",
    "at",
    "is",
    "was",
    "by",
    "from",
    "as",
    "that",
    "this",
    "it",
    "be",
    "are",
}


@dataclass
class TimelineRow:
    date_text: str
    event_type: str
    provider: str
    fact_lines: list[str]
    citation_line: str


def _extract_timeline_slice(report_text: str) -> str:
    low = report_text.lower()
    start = low.find("chronological medical timeline")
    if start < 0:
        return report_text
    end_candidates = [
        low.find("top 10 case-driving events", start + 1),
        low.find("appendix a:", start + 1),
    ]
    ends = [e for e in end_candidates if e > start]
    end = min(ends) if ends else len(report_text)
    return report_text[start:end]


def _extract_top10_slice(report_text: str) -> str:
    low = report_text.lower()
    start = low.find("top 10 case-driving events")
    if start < 0:
        return ""
    end_candidates = [
        low.find("appendix a:", start + 1),
        low.find("appendix b:", start + 1),
    ]
    ends = [e for e in end_candidates if e > start]
    end = min(ends) if ends else len(report_text)
    return report_text[start:end]


def _extract_appendix_b_slice(report_text: str) -> str:
    low = report_text.lower()
    start = low.find("appendix b:")
    if start < 0:
        return ""
    end_candidates = [
        low.find("appendix c:", start + 1),
        low.find("appendix d:", start + 1),
        low.find("appendix e:", start + 1),
        low.find("appendix f:", start + 1),
    ]
    ends = [e for e in end_candidates if e > start]
    end = min(ends) if ends else len(report_text)
    return report_text[start:end]


def _parse_timeline_rows(timeline_text: str) -> list[TimelineRow]:
    rows: list[TimelineRow] = []
    current: TimelineRow | None = None
    for raw in timeline_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = ROW_RE.match(line)
        if m:
            if current:
                rows.append(current)
            current = TimelineRow(
                date_text=m.group(1).strip(),
                event_type=m.group(2).strip(),
                provider="",
                fact_lines=[],
                citation_line="",
            )
            continue
        if current is None:
            continue
        if line.lower().startswith("facility/clinician:"):
            current.provider = line.split(":", 1)[1].strip()
        elif line.lower().startswith("citation(s):"):
            current.citation_line = line
        else:
            current.fact_lines.append(line)
    if current:
        rows.append(current)
    return rows


def _rows_from_projection_entries(entries: list[Any]) -> list[TimelineRow]:
    rows: list[TimelineRow] = []
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
        # Keep fallback rows litigation-useful; do not import placeholder-heavy projection rows.
        if _non_stopword_token_count(facts_text) < 12:
            continue
        if _fact_category_count(facts_text) < 2:
            continue
        if PLACEHOLDER_RE.search(facts_text):
            continue
        date_text = "Undated"
        m = DATE_RE.search(getattr(e, "date_display", "") or "")
        if m:
            date_text = m.group(1)
        rows.append(
            TimelineRow(
                date_text=date_text,
                event_type=str(getattr(e, "event_type_display", "") or ""),
                provider=str(getattr(e, "provider_display", "") or ""),
                fact_lines=facts,
                citation_line=f"Citation(s): {citation}",
            )
        )
    return rows


def _merge_rows(parsed_rows: list[TimelineRow], projection_rows: list[TimelineRow]) -> list[TimelineRow]:
    merged: list[TimelineRow] = []
    seen: set[tuple[str, str, str]] = set()
    for row in parsed_rows + projection_rows:
        key = (row.date_text.strip().lower(), row.event_type.strip().lower(), row.citation_line.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _non_stopword_token_count(text: str) -> int:
    tokens = re.findall(r"[a-zA-Z0-9/-]+", (text or "").lower())
    return sum(1 for t in tokens if t not in STOPWORDS)


def _fact_category_count(text: str) -> int:
    categories = 0
    if PAIN_RE.search(text):
        categories += 1
    if ROM_RE.search(text):
        categories += 1
    if STRENGTH_RE.search(text):
        categories += 1
    if VITALS_RE.search(text):
        categories += 1
    if MED_RE.search(text) and DOSAGE_RE.search(text):
        categories += 1
    if LEVEL_RE.search(text):
        categories += 1
    if DX_RE.search(text):
        categories += 1
    if ENCOUNTER_RE.search(text):
        categories += 1
    return categories


def _parse_header_timeframe(report_text: str) -> tuple[date | None, date | None]:
    m = re.search(r"Treatment Timeframe:\s*(\d{4}-\d{2}-\d{2})\s*to\s*(\d{4}-\d{2}-\d{2})", report_text, re.IGNORECASE)
    if not m:
        return None, None
    try:
        return date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
    except ValueError:
        return None, None


def _extract_date_from_display(display: str) -> date | None:
    m = DATE_RE.search(display or "")
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _robust_window(dates: list[date]) -> tuple[date | None, date | None]:
    if not dates:
        return None, None
    ordered = sorted(dates)
    if len(ordered) >= 3:
        # Trim isolated far-end outliers to avoid header/window hard-fails on one bad date.
        if (ordered[-1] - ordered[-2]).days > 21:
            ordered = ordered[:-1]
        if len(ordered) >= 3 and (ordered[1] - ordered[0]).days > 21:
            ordered = ordered[1:]
    if not ordered:
        return None, None
    return ordered[0], ordered[-1]


def _substantive_entry(entry: Any) -> bool:
    citation = getattr(entry, "citation_display", "") or ""
    if not citation.strip():
        return False
    facts = [str(f or "") for f in (getattr(entry, "facts", []) or [])]
    txt = " ".join(facts)
    token_count = len(re.findall(r"[a-zA-Z0-9/-]+", txt))
    return token_count >= 4 and not is_noise_span(txt)


def _source_bucket_presence(page_text_by_number: dict[int, str]) -> set[str]:
    present: set[str] = set()
    for txt in (page_text_by_number or {}).values():
        if not txt:
            continue
        for bucket, rex in BUCKET_SIGNALS.items():
            if rex.search(txt):
                present.add(bucket)
    return present


def _timeline_bucket_presence(rows: list[TimelineRow]) -> set[str]:
    present: set[str] = set()
    for row in rows:
        blob = f"{row.event_type} {' '.join(row.fact_lines)}".lower()
        if re.search(r"\b(emergency|ed)\b", blob):
            present.add("ED")
        if re.search(r"\b(mri|impression|imaging)\b", blob):
            present.add("MRI")
        if re.search(r"\b(therapy visit|pt eval|physical therapy)\b", blob):
            present.add("PT_EVAL")
        if re.search(r"\b(ortho|orthopedic|orthopaedic)\b", blob):
            present.add("ORTHO")
        if re.search(r"\b(procedure|injection|fluoroscopy|depo-medrol|lidocaine)\b", blob):
            present.add("PROCEDURE")
    return present


def _projection_bucket_presence(entries: list[Any]) -> set[str]:
    present: set[str] = set()
    for e in entries or []:
        blob = (
            f"{str(getattr(e, 'event_type_display', '') or '')} "
            f"{' '.join(str(f or '') for f in (getattr(e, 'facts', []) or []))}"
        ).lower()
        if re.search(r"\b(emergency|ed|chief complaint|triage)\b", blob):
            present.add("ED")
        if re.search(r"\b(mri|impression|imaging)\b", blob):
            present.add("MRI")
        if re.search(r"\b(therapy visit|pt eval|physical therapy)\b", blob):
            present.add("PT_EVAL")
        if re.search(r"\b(ortho|orthopedic|orthopaedic)\b", blob):
            present.add("ORTHO")
        if re.search(r"\b(procedure|injection|fluoroscopy|depo-medrol|lidocaine|epidural)\b", blob):
            present.add("PROCEDURE")
    return present


def build_luqa_report(report_text: str, ctx: dict[str, Any]) -> dict[str, Any]:
    timeline_text = _extract_timeline_slice(report_text)
    top10_text = _extract_top10_slice(report_text)
    appendix_b_text = _extract_appendix_b_slice(report_text)
    parsed_rows = _parse_timeline_rows(timeline_text)
    projection_entries = list(ctx.get("projection_entries", []) or [])
    projection_rows = _rows_from_projection_entries(projection_entries)
    used_projection_fallback = False
    rows = parsed_rows
    if len(parsed_rows) < max(2, min(5, len(projection_rows) // 2)):
        rows = _merge_rows(parsed_rows, projection_rows)
        used_projection_fallback = True
    row_count = len(rows)

    failures: list[dict[str, Any]] = []
    penalties = 0.0
    hard_fail = False

    meta_matches = list(META_RE.finditer(timeline_text))
    meta_hits = len(meta_matches)
    if meta_hits > 0:
        hard_fail = True
        failures.append(
            {
                "code": "LUQA_META_LANGUAGE_BAN",
                "severity": "hard",
                "message": f"Meta-language found in timeline: {meta_hits} hit(s).",
                "examples": [timeline_text[max(0, m.start() - 40) : min(len(timeline_text), m.end() + 60)] for m in meta_matches[:3]],
            }
        )
        penalties += 20

    render_quality_defects: list[str] = []
    if CONTROL_CHAR_RE.search(timeline_text) or CONTROL_CHAR_RE.search(top10_text):
        render_quality_defects.append("control_character_artifact")
    if re.search(r'"\s*[^"]*?\."\.', timeline_text):
        render_quality_defects.append("double_period_after_quoted_snippet")
    if re.search(r"\b(?:includ|assessm|therap|diagnos|manageme)\b[\".]?\s*$", timeline_text, re.IGNORECASE | re.MULTILINE):
        render_quality_defects.append("truncated_fragment_suffix")
    if re.search(r"\b(?:and|or|with|to)\.\s*$", top10_text, re.IGNORECASE | re.MULTILINE):
        render_quality_defects.append("orphan_conjunction_ending")
    if re.search(r"(?im)^\s*[•\u2022\x7f]\s*date not documented\b", top10_text):
        render_quality_defects.append("undated_top10_item")
    if re.search(r"\bdischarge summary\b", appendix_b_text, re.IGNORECASE):
        render_quality_defects.append("dx_appendix_contains_discharge_summary_text")
    if not used_projection_fallback:
        for row in rows:
            if "orthopedic" in (row.event_type or "").lower():
                has_plan = any(f.lower().startswith("plan:") for f in row.fact_lines)
                if not has_plan:
                    render_quality_defects.append("ortho_row_missing_plan")
                    break
    if render_quality_defects:
        hard_fail = True
        failures.append(
            {
                "code": "LUQA_RENDER_QUALITY_SANITY",
                "severity": "hard",
                "message": "Rendered chronology contains litigation-blocking formatting/semantic defects.",
                "examples": render_quality_defects[:5],
            }
        )

    placeholders = 0
    fact_dense = 0
    verbatim_rows = 0
    duplicate_counter: Counter[tuple[str, str, str, str]] = Counter()
    duplicate_examples: list[str] = []
    rows_with_noise_citations = 0
    all_noise_pages = {p for p, txt in (ctx.get("page_text_by_number") or {}).items() if is_noise_span(txt or "")}

    for row in rows:
        facts_text = " ".join(row.fact_lines)
        tokens = _non_stopword_token_count(facts_text)
        categories = _fact_category_count(facts_text)
        is_placeholder_text = bool(PLACEHOLDER_RE.search(facts_text))
        is_low_signal = tokens < 8 and categories == 0
        if is_placeholder_text or is_low_signal:
            placeholders += 1
        if categories >= 2:
            fact_dense += 1
        if any('"' in ln for ln in row.fact_lines) or any(
            (_non_stopword_token_count(ln) >= 8 and not META_RE.search(ln or ""))
            for ln in row.fact_lines
        ):
            verbatim_rows += 1

        snippet_norm = re.sub(r"\s+", " ", facts_text.lower()).strip()
        if snippet_norm:
            snippet_hash = hashlib.sha1(snippet_norm.encode("utf-8")).hexdigest()[:16]
            fp = (row.date_text, row.provider.lower(), row.event_type.lower(), snippet_hash)
            duplicate_counter[fp] += 1

        citation_pages = {int(p) for p in re.findall(r"p\.\s*(\d+)", row.citation_line)}
        if citation_pages and any(p in all_noise_pages for p in citation_pages):
            rows_with_noise_citations += 1

    placeholder_ratio = (placeholders / row_count) if row_count else 0.0
    fact_density_ratio = (fact_dense / row_count) if row_count else 0.0
    verbatim_ratio = (verbatim_rows / row_count) if row_count else 0.0

    if placeholder_ratio > 0.20:
        hard_fail = True
        failures.append(
            {
                "code": "LUQA_PLACEHOLDER_RATIO",
                "severity": "hard",
                "message": f"Placeholder ratio too high: {placeholder_ratio:.3f}",
                "examples": [r.fact_lines[0] if r.fact_lines else "" for r in rows[:3]],
            }
        )
    penalties += min(30.0, placeholder_ratio * 30.0)

    if fact_density_ratio < 0.30:
        hard_fail = True
        failures.append(
            {
                "code": "LUQA_FACT_DENSITY",
                "severity": "hard",
                "message": f"Fact-dense ratio too low: {fact_density_ratio:.3f}",
                "examples": [r.fact_lines[0] if r.fact_lines else "" for r in rows[:3]],
            }
        )
    elif fact_density_ratio < 0.60:
        penalties += min(30.0, ((0.60 - fact_density_ratio) / 0.60) * 30.0)

    if verbatim_ratio < 0.70:
        hard_fail = True
        failures.append(
            {
                "code": "LUQA_VERBATIM_ANCHOR_RATIO",
                "severity": "hard",
                "message": f"Verbatim ratio below hard threshold: {verbatim_ratio:.3f}",
                "examples": [r.fact_lines[0] if r.fact_lines else "" for r in rows[:3]],
            }
        )
    elif verbatim_ratio < 0.85:
        penalties += min(30.0, ((0.85 - verbatim_ratio) / 0.85) * 30.0)

    duplicate_rows = 0
    for fp, count in duplicate_counter.items():
        if count >= 2:
            duplicate_rows += count - 1
        if count >= 3 and len(duplicate_examples) < 3:
            duplicate_examples.append(f"{fp[0]} | {fp[2]} | repeats={count}")
    duplicate_rows_ratio = (duplicate_rows / row_count) if row_count else 0.0
    if duplicate_examples or duplicate_rows_ratio > 0.10:
        hard_fail = True
        failures.append(
            {
                "code": "LUQA_DUPLICATE_SNIPPETS",
                "severity": "hard",
                "message": f"Duplicate snippet ratio too high: {duplicate_rows_ratio:.3f}",
                "examples": duplicate_examples[:3],
            }
        )
    penalties += min(20.0, duplicate_rows_ratio * 20.0)

    # Care window integrity.
    header_start, header_end = _parse_header_timeframe(report_text)
    substantive_dates: list[date] = []
    for e in projection_entries:
        d = _extract_date_from_display(getattr(e, "date_display", ""))
        if d is not None and _substantive_entry(e):
            substantive_dates.append(d)
    event_start, event_end = _robust_window(substantive_dates)
    care_window_mismatch = False
    # Validate containment (small tolerance) so header timeframe does not exclude
    # substantive cited event dates.
    if header_start and event_start and (header_start - event_start).days > 1:
        care_window_mismatch = True
    if header_end and event_end and (event_end - header_end).days > 1:
        care_window_mismatch = True
    if care_window_mismatch:
        hard_fail = True
        failures.append(
            {
                "code": "LUQA_CARE_WINDOW_INTEGRITY",
                "severity": "hard",
                "message": "Header treatment timeframe does not match substantive cited event window.",
                "examples": [f"header={header_start}..{header_end}", f"events={event_start}..{event_end}"],
            }
        )

    # Required buckets when present.
    source_buckets = _source_bucket_presence(ctx.get("page_text_by_number") or {})
    timeline_buckets = _timeline_bucket_presence(rows) | _projection_bucket_presence(projection_entries)
    missing_buckets = sorted(source_buckets - timeline_buckets)
    if missing_buckets:
        hard_fail = True
        failures.append(
            {
                "code": "LUQA_REQUIRED_BUCKETS_WHEN_PRESENT",
                "severity": "hard",
                "message": f"Required buckets missing from timeline: {', '.join(missing_buckets)}",
                "examples": missing_buckets[:5],
            }
        )

    noise_rows_ratio = (rows_with_noise_citations / row_count) if row_count else 0.0
    if all_noise_pages and noise_rows_ratio > 0.05:
        hard_fail = True
        failures.append(
            {
                "code": "LUQA_NOISE_SUPPRESSION_RATE",
                "severity": "hard",
                "message": f"Too many timeline rows cite noise pages: {noise_rows_ratio:.3f}",
                "examples": [f"noise_rows={rows_with_noise_citations}", f"rows={row_count}"],
            }
        )

    score = int(round(max(0.0, min(100.0, 100.0 - penalties))))
    if hard_fail:
        score = min(score, 60)
    luqa_pass = bool((not hard_fail) and score >= 90)

    return {
        "luqa_pass": luqa_pass,
        "luqa_score_0_100": score,
        "failures": failures,
        "metrics": {
            "meta_hits": meta_hits,
            "placeholder_ratio": round(placeholder_ratio, 3),
            "duplicate_lines": duplicate_rows,
            "duplicate_rows_ratio": round(duplicate_rows_ratio, 3),
            "fact_density_ratio": round(fact_density_ratio, 3),
            "verbatim_ratio": round(verbatim_ratio, 3),
            "care_window_mismatch": care_window_mismatch,
            "missing_buckets": missing_buckets,
            "timeline_row_count": row_count,
            "noise_rows_ratio": round(noise_rows_ratio, 3),
            "render_quality_defect_count": len(render_quality_defects),
        },
    }
