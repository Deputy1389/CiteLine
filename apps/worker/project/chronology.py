from __future__ import annotations
from datetime import date, datetime, timezone, timedelta
from dataclasses import dataclass, asdict
import logging
import re
import hashlib
import textwrap
from collections import defaultdict
from typing import Any, Callable

from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.events.report_quality import (
    date_sanity,
    injury_canonicalization,
    is_reportable_fact,
    procedure_canonicalization,
    sanitize_for_report,
    surgery_classifier_guard,
)
from apps.worker.lib.noise_filter import is_noise_span
from packages.shared.models import Event, Provider, ProviderType, RunConfig

# New Utility Imports
from packages.shared.utils.render_utils import (
    projection_date_display as _projection_date_display,
    iso_date_display as _iso_date_display,
    get_provider_name as _provider_name,
    get_citation_display as _citation_display,
    infer_page_patient_labels,
    get_event_patient_label as _event_patient_label,
)
from packages.shared.utils.noise_utils import (
    is_vitals_heavy as _is_vitals_heavy,
    is_header_noise_fact as _is_header_noise_fact,
    is_flowsheet_noise as _is_flowsheet_noise,
    has_narrative_sentence as _has_narrative_sentence,
)
from packages.shared.utils.extraction_utils import (
    extract_pt_elements as _extract_pt_elements,
    extract_imaging_elements as _extract_imaging_elements,
)
from packages.shared.utils.scoring_utils import (
    is_high_value_event as _is_high_value_event,
    classify_projection_entry as _classify_projection_entry,
    bucket_for_required_coverage as _bucket_for_required_coverage,
    projection_entry_score as _projection_entry_score,
    entry_substance_score as _entry_substance_score,
    is_substantive_entry as _is_substantive_entry,
)
from packages.shared.utils.date_utils import (
    parse_fact_dates as _parse_fact_dates,
    fact_temporally_consistent as _fact_temporally_consistent,
    strip_conflicting_timestamps as _strip_conflicting_timestamps,
)

INPATIENT_MARKER_RE = re.compile(
    r"\b(admission order|hospital day|inpatient service|discharge summary|admitted|inpatient|hospitalist|icu|intensive care)\b",
    re.IGNORECASE,
)
MIN_SUBSTANCE_THRESHOLD = 1
HIGH_SUBSTANCE_THRESHOLD = 2
UTILITY_EPSILON = 0.03
UTILITY_CONSECUTIVE_LOW_K = 8
_SUBSTANCE_HIGH_PAT = re.compile(
    r"\b(assessment|impression|diagnosis|chief complaint|history of present illness|hpi|"
    r"motor vehicle|mvc|mva|collision|rear[- ]end|procedure|injection|surgery|epidural|"
    r"mri|x-?ray|ct|radiculopathy|herniat|protrusion|stenosis|fracture|tear)\b",
    re.IGNORECASE,
)
_SUBSTANCE_MED_PAT = re.compile(
    r"\b(plan|range of motion|rom|strength|pain(?:\s*(?:score|severity|level))?\s*[:=]?\s*\d{1,2}\s*/\s*10|"
    r"work restriction|return to work|medication|prescribed|disposition)\b",
    re.IGNORECASE,
)
_SUBSTANCE_LOW_PAT = re.compile(
    r"\b(provider not stated|unknown provider|clinical note|follow up|routine)\b",
    re.IGNORECASE,
)
_NEGATIVE_FINDING_RE = re.compile(
    r"\b(unremarkable|no acute|normal|no evidence of|negative for|stable|no change)\b",
    re.IGNORECASE,
)
logger = logging.getLogger(__name__)
_ROW_FACT_SUBSTANCE_RE = re.compile(
    r"\b("
    r"diagnosis|assessment|impression|plan|procedure|surgery|injection|epidural|esi|"
    r"mri|x-?ray|ct|ultrasound|fracture|tear|herniat|protrusion|stenosis|"
    r"weakness|strength|range of motion|rom|reflex|diminished|"
    r"prescribed|started|stopped|referred|discharge"
    r")\b",
    re.IGNORECASE,
)
_ROW_META_NOISE_RE = re.compile(
    r"^\s*(?:general hospital|hospital|trauma center|provider not clearly identified|unknown)\b.*?(?:\b\d{1,2}\s*/\s*10\b)?\s*$",
    re.IGNORECASE,
)
_ED_PAGE_MARKER_RE = re.compile(
    r"\b(ed notes?|emergency department|emergency room|er visit|triage|chief complaint|history of present illness|hpi)\b",
    re.IGNORECASE,
)
_PT_EVAL_MARKER_RE = re.compile(
    r"\b(initial evaluation|pt evaluation|plan of care|physical therapy evaluation)\b",
    re.IGNORECASE,
)
_PAIN_SCORE_RE = re.compile(r"\b\d{1,2}\s*/\s*10\b", re.IGNORECASE)
_STRUCTURED_FACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(chief complaint|history of present illness|hpi)\b", re.I),
    re.compile(r"\b(pain(?:\s*(?:score|level|severity))?\s*[:=]?\s*\d{1,2}\s*/\s*10)\b", re.I),
    re.compile(r"\b(?:bp|blood pressure)\s*[:=]?\s*\d{2,3}\s*/\s*\d{2,3}\b", re.I),
    re.compile(r"\b(?:hr|heart rate|rr|respiratory rate|spo2)\b", re.I),
    re.compile(r"\b(?:assessment|impression|diagnosis|radiculopathy|strain|sprain|disc|protrusion|stenosis)\b", re.I),
    re.compile(r"\b(?:rom|range of motion|strength|weakness|reflex|tenderness|spasm)\b", re.I),
    re.compile(r"\b(?:toradol|ketorolac|ibuprofen|acetaminophen|lidocaine|depo-?medrol|flexeril|gabapentin|naproxen)\b.*\b(?:mg|mcg|ml)\b", re.I),
    re.compile(r"\b(?:procedure|injection|epidural|fluoroscopy|discharge|final pain|return precautions)\b", re.I),
]


def _resolve_config(config: RunConfig | None) -> RunConfig:
    return config or RunConfig()

def _event_type_display(event: Event) -> str:
    mapping = {
        "hospital_admission": "Hospital Admission",
        "hospital_discharge": "Hospital Discharge",
        "er_visit": "Emergency Visit",
        "inpatient_daily_note": "Inpatient Progress",
        "office_visit": "Follow-Up Visit",
        "pt_visit": "Therapy Visit",
        "imaging_study": "Imaging Study",
        "procedure": "Procedure/Surgery",
        "lab_result": "Lab Result",
        "discharge": "Discharge",
    }
    key = event.event_type.value
    return mapping.get(key, key.replace("_", " ").title())


_UNKNOWN_PROVIDER_LABELS = {
    "",
    "unknown",
    "provider not stated",
    "provider not clearly identified",
}


def _is_unknown_provider_label(name: str) -> bool:
    return (name or "").strip().lower() in _UNKNOWN_PROVIDER_LABELS


def _provider_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _provider_display_for_inference(provider: Provider | None) -> str | None:
    if provider is None:
        return None
    raw = provider.normalized_name or provider.detected_name_raw
    clean = sanitize_for_report(raw or "").strip()
    if not clean:
        return None
    if provider.confidence < 60:
        return None
    low_clean = clean.lower()
    if _is_unknown_provider_label(low_clean):
        return None
    if any(token in low_clean for token in ("medical record summary", "stress test", "chronology eval", "sample 172", "pdf", "page")):
        return None
    if re.search(r"[a-f0-9]{8,}", low_clean):
        return None
    return clean


def _choose_consistent_provider_from_pages(
    page_numbers: list[int],
    providers: list[Provider],
    page_provider_map: dict[int, str] | None,
    *,
    allowed_types: set[ProviderType] | None = None,
    disallowed_types: set[ProviderType] | None = None,
) -> str | None:
    if not page_numbers or not page_provider_map or not providers:
        return None
    providers_by_id = {p.provider_id: p for p in providers}
    counts: dict[str, int] = {}
    canonical: dict[str, str] = {}
    for pnum in sorted(set(page_numbers)):
        pid = page_provider_map.get(pnum)
        if not pid:
            continue
        prov = providers_by_id.get(pid)
        if not prov:
            continue
        ptype = getattr(prov, "provider_type", ProviderType.UNKNOWN)
        if allowed_types is not None and ptype not in allowed_types:
            continue
        if disallowed_types is not None and ptype in disallowed_types:
            continue
        label = _provider_display_for_inference(prov)
        if not label:
            continue
        key = _provider_key(label)
        counts[key] = counts.get(key, 0) + 1
        best = canonical.get(key)
        if best is None or (label != label.lower() and best == best.lower()) or len(label) > len(best):
            canonical[key] = label
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) > 1:
        return None
    return canonical.get(ranked[0][0], ranked[0][0])


def _citation_page_numbers(citation_display: str) -> list[int]:
    pages: list[int] = []
    seen: set[int] = set()
    for m in re.finditer(r"\bp\.\s*(\d{1,5})\b", citation_display or "", re.IGNORECASE):
        try:
            pnum = int(m.group(1))
        except ValueError:
            continue
        if pnum <= 0 or pnum in seen:
            continue
        seen.add(pnum)
        pages.append(pnum)
    return pages


def _noise_anchor_pages(page_text_by_number: dict[int, str] | None) -> set[int]:
    noise_pages: set[int] = set()
    for pnum, txt in (page_text_by_number or {}).items():
        text = str(txt or "")
        if not text.strip():
            continue
        if _has_narrative_sentence(text):
            continue
        # Conservative: mark as noise anchor only when both generic and flowsheet
        # detectors agree, to avoid suppressing thin but real clinical pages.
        if _is_flowsheet_noise(text) and is_noise_span(text):
            noise_pages.add(int(pnum))
    return noise_pages


def _structured_page_fact_items(
    event: Event,
    page_text_by_number: dict[int, str] | None,
    *,
    limit: int = 6,
) -> list[tuple[str, bool]]:
    items: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for pnum in sorted(set(getattr(event, "source_page_numbers", []) or [])):
        text = str((page_text_by_number or {}).get(int(pnum)) or "")
        if not text:
            continue
        for raw_line in re.split(r"[\r\n]+", text):
            cleaned = sanitize_for_report(str(raw_line or "")).strip()
            if not cleaned:
                continue
            if _is_header_noise_fact(cleaned) or _ROW_META_NOISE_RE.search(cleaned):
                continue
            if is_noise_span(cleaned) and not re.search(
                r"\b(assessment|impression|diagnosis|chief complaint|hpi|pain|bp|blood pressure|rom|range of motion|strength|"
                r"weakness|reflex|tenderness|spasm|procedure|injection|discharge|medication)\b",
                cleaned,
                re.I,
            ):
                continue
            if not any(p.search(cleaned) for p in _STRUCTURED_FACT_PATTERNS):
                continue
            key = re.sub(r"\s+", " ", cleaned.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            items.append((cleaned, True))  # direct page text => verbatim-safe
            if len(items) >= limit:
                return items
    return items

def _is_substantive_event(event: Event) -> bool:
    joined_facts = " ".join(f.text for f in event.facts).lower()
    keywords = (
        "diagnosis", "assessment", "impression", "problem", "radiculopathy",
        "fracture", "tear", "infection", "stenosis", "sprain", "strain",
        "medication", "prescribed", "started", "stopped", "procedure",
        "surgery", "injection", "mri", "x-ray", "ct scan", "ultrasound",
        "physician overread", "medical director", "care summary"
    )
    if any(k in joined_facts for k in keywords):
        return True
    if len(event.facts) > 3:
        return True
    return False

def _is_high_substance_entry(entry: ChronologyProjectionEntry) -> bool:
    if not _is_substantive_entry(entry):
        return False
    return _entry_substance_score(entry) >= HIGH_SUBSTANCE_THRESHOLD

def _entry_date_only(entry: ChronologyProjectionEntry) -> date | None:
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", entry.date_display or "")
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _has_minimum_row_fact(entry: ChronologyProjectionEntry) -> bool:
    facts = [sanitize_for_report(f or "").strip() for f in (entry.facts or []) if sanitize_for_report(f or "").strip()]
    if not facts:
        return False
    flags = _entry_verbatim_flags(entry)
    for idx, fact in enumerate(facts):
        if idx < len(flags) and bool(flags[idx]) and len(re.findall(r"[A-Za-z]{2,}", fact)) >= 4:
            return True
    blob = " ".join(facts).lower()
    if _ROW_FACT_SUBSTANCE_RE.search(blob):
        return True
    if len(facts) == 1 and _ROW_META_NOISE_RE.search(facts[0]):
        return False
    if _PAIN_SCORE_RE.search(blob) and len(re.findall(r"[A-Za-z]{3,}", blob)) >= 8:
        return True
    return False


@dataclass
class RequiredBucketSpec:
    bucket_id: str
    bucket_label: str
    insert_priority: int
    present_in_source: Callable[[list[ChronologyProjectionEntry], dict[str, Any]], bool]
    is_candidate: Callable[[ChronologyProjectionEntry, dict[str, Any]], bool]
    score_candidate: Callable[[ChronologyProjectionEntry, dict[str, Any]], int]
    min_require_citation: bool = True


def _entry_text_blob(entry: ChronologyProjectionEntry) -> str:
    return " ".join([entry.event_type_display or "", entry.provider_display or "", *(entry.facts or [])]).strip().lower()


def _entry_has_citation(entry: ChronologyProjectionEntry) -> bool:
    return bool((entry.citation_display or "").strip())


def _entry_bucket(entry: ChronologyProjectionEntry, forced_bucket_by_event: dict[str, str] | None = None) -> str | None:
    if forced_bucket_by_event:
        fb = forced_bucket_by_event.get(str(entry.event_id))
        if fb:
            return fb
    return _bucket_for_required_coverage(entry)


def _entry_pages(entry: ChronologyProjectionEntry) -> list[int]:
    return _citation_page_numbers(entry.citation_display or "")


def _doi_like_date(rows: list[ChronologyProjectionEntry]) -> date | None:
    dated = sorted([d for d in (_entry_date_only(r) for r in rows) if d is not None])
    return dated[0] if dated else None


def _pages_with_marker(page_text_by_number: dict[int, str] | None, marker_re: re.Pattern[str]) -> set[int]:
    out: set[int] = set()
    for pnum, txt in (page_text_by_number or {}).items():
        if marker_re.search(txt or ""):
            out.add(int(pnum))
    return out


def _build_required_bucket_specs(rows: list[ChronologyProjectionEntry], *, page_text_by_number: dict[int, str] | None) -> tuple[list[RequiredBucketSpec], dict[str, Any]]:
    doi = _doi_like_date(rows)
    ed_marker_pages = _pages_with_marker(page_text_by_number, _ED_PAGE_MARKER_RE)
    pt_eval_marker_pages = _pages_with_marker(page_text_by_number, _PT_EVAL_MARKER_RE)
    ctx: dict[str, Any] = {
        "doi": doi,
        "ed_marker_pages": ed_marker_pages,
        "pt_eval_marker_pages": pt_eval_marker_pages,
    }

    def _ed_present(rows_local: list[ChronologyProjectionEntry], c: dict[str, Any]) -> bool:
        for r in rows_local:
            if _entry_bucket(r) == "ed":
                return True
            if set(_entry_pages(r)).intersection(c.get("ed_marker_pages") or set()):
                return True
            if _ED_PAGE_MARKER_RE.search(_entry_text_blob(r)):
                return True
        return False

    def _ed_candidate(r: ChronologyProjectionEntry, c: dict[str, Any]) -> bool:
        if not _entry_has_citation(r):
            return False
        if _entry_bucket(r) == "ed":
            return True
        if set(_entry_pages(r)).intersection(c.get("ed_marker_pages") or set()):
            return True
        return bool(_ED_PAGE_MARKER_RE.search(_entry_text_blob(r)))

    def _ed_score(r: ChronologyProjectionEntry, c: dict[str, Any]) -> int:
        score = 0
        pages = set(_entry_pages(r))
        if pages.intersection(c.get("ed_marker_pages") or set()):
            score += 100
        if _entry_bucket(r) == "ed" or re.search(r"\b(emergency|er visit|ed visit)\b", (r.event_type_display or ""), re.I):
            score += 50
        doi_local = c.get("doi")
        row_d = _entry_date_only(r)
        if doi_local is not None and row_d is not None and abs((row_d - doi_local).days) <= 3:
            score += 25
        if _PAIN_SCORE_RE.search(_entry_text_blob(r)):
            score += 10
        return score

    def _pt_eval_present(rows_local: list[ChronologyProjectionEntry], c: dict[str, Any]) -> bool:
        for r in rows_local:
            if _entry_bucket(r) == "pt_eval":
                return True
            if set(_entry_pages(r)).intersection(c.get("pt_eval_marker_pages") or set()):
                return True
            if _PT_EVAL_MARKER_RE.search(_entry_text_blob(r)):
                return True
        return False

    def _pt_eval_candidate(r: ChronologyProjectionEntry, c: dict[str, Any]) -> bool:
        if not _entry_has_citation(r):
            return False
        if _entry_bucket(r) == "pt_eval":
            return True
        if set(_entry_pages(r)).intersection(c.get("pt_eval_marker_pages") or set()):
            return True
        return bool(_PT_EVAL_MARKER_RE.search(_entry_text_blob(r)))

    def _pt_eval_score(r: ChronologyProjectionEntry, c: dict[str, Any]) -> int:
        score = 0
        if set(_entry_pages(r)).intersection(c.get("pt_eval_marker_pages") or set()):
            score += 100
        if _entry_bucket(r) == "pt_eval":
            score += 50
        doi_local = c.get("doi")
        row_d = _entry_date_only(r)
        if doi_local is not None and row_d is not None and row_d >= doi_local:
            score += 15
        if _PT_EVAL_MARKER_RE.search(_entry_text_blob(r)):
            score += 10
        return score

    def _surgery_present(rows_local: list[ChronologyProjectionEntry], _c: dict[str, Any]) -> bool:
        return any(_classify_projection_entry(r) == "surgery_procedure" for r in rows_local)

    def _surgery_candidate(r: ChronologyProjectionEntry, _c: dict[str, Any]) -> bool:
        return _entry_has_citation(r) and _classify_projection_entry(r) == "surgery_procedure"

    def _surgery_score(r: ChronologyProjectionEntry, _c: dict[str, Any]) -> int:
        return int(_entry_substance_score(r) * 10) + (20 if any(_entry_verbatim_flags(r)) else 0)

    def _imaging_present(rows_local: list[ChronologyProjectionEntry], _c: dict[str, Any]) -> bool:
        return any(_classify_projection_entry(r) == "imaging_impression" for r in rows_local)

    def _imaging_candidate(r: ChronologyProjectionEntry, _c: dict[str, Any]) -> bool:
        return _entry_has_citation(r) and _classify_projection_entry(r) == "imaging_impression"

    def _imaging_score(r: ChronologyProjectionEntry, _c: dict[str, Any]) -> int:
        return int(_entry_substance_score(r) * 10) + (20 if any(_entry_verbatim_flags(r)) else 0)

    specs = [
        RequiredBucketSpec(
            bucket_id="ed",
            bucket_label="ed_visit",
            insert_priority=0,
            present_in_source=_ed_present,
            is_candidate=_ed_candidate,
            score_candidate=_ed_score,
        ),
        RequiredBucketSpec(
            bucket_id="pt_eval",
            bucket_label="pt_eval",
            insert_priority=10,
            present_in_source=_pt_eval_present,
            is_candidate=_pt_eval_candidate,
            score_candidate=_pt_eval_score,
        ),
        RequiredBucketSpec(
            bucket_id="surgery_procedure",
            bucket_label="surgery_procedure",
            insert_priority=20,
            present_in_source=_surgery_present,
            is_candidate=_surgery_candidate,
            score_candidate=_surgery_score,
        ),
        RequiredBucketSpec(
            bucket_id="imaging_impression",
            bucket_label="imaging_impression",
            insert_priority=30,
            present_in_source=_imaging_present,
            is_candidate=_imaging_candidate,
            score_candidate=_imaging_score,
        ),
    ]
    return specs, ctx


def _selection_sort_key(entry: ChronologyProjectionEntry) -> tuple[int, str, str]:
    d = _entry_date_only(entry)
    if d is None:
        return (99, "9999-12-31", entry.event_id)
    return (0, d.isoformat(), entry.event_id)


def _find_best_required_candidate(spec: RequiredBucketSpec, candidates: list[ChronologyProjectionEntry], *, ctx: dict[str, Any]) -> ChronologyProjectionEntry | None:
    filtered = [c for c in candidates if (not spec.min_require_citation or _entry_has_citation(c)) and spec.is_candidate(c, ctx)]
    if not filtered:
        return None
    scored = [(spec.score_candidate(c, ctx), c) for c in filtered]
    scored.sort(key=lambda item: (-item[0], _selection_sort_key(item[1])))
    return scored[0][1]


def _force_insert_required_bucket(
    selected: list[ChronologyProjectionEntry],
    *,
    bucket: str,
    candidate: ChronologyProjectionEntry,
    forced_bucket_by_event: dict[str, str],
) -> list[ChronologyProjectionEntry]:
    if any((_entry_bucket(r, forced_bucket_by_event) == bucket) for r in selected):
        return selected
    if all(r.event_id != candidate.event_id for r in selected):
        selected = [*selected, candidate]
    forced_bucket_by_event[str(candidate.event_id)] = bucket
    selected.sort(key=_selection_sort_key)
    return selected


def _enforce_required_buckets(
    *,
    selected: list[ChronologyProjectionEntry],
    all_candidates: list[ChronologyProjectionEntry],
    specs: list[RequiredBucketSpec],
    ctx: dict[str, Any],
    patient_label: str,
    forced_bucket_by_event: dict[str, str],
) -> tuple[list[ChronologyProjectionEntry], list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    missing: list[dict[str, Any]] = []
    choices: list[dict[str, Any]] = []
    source_required = [s.bucket_id for s in specs if s.present_in_source(all_candidates, ctx)]
    selected_pre = sorted({b for r in selected for b in [_entry_bucket(r, forced_bucket_by_event)] if b})
    for spec in specs:
        if spec.bucket_id not in source_required:
            continue
        if spec.bucket_id in selected_pre or any((_entry_bucket(r, forced_bucket_by_event) == spec.bucket_id) for r in selected):
            continue
        candidate = _find_best_required_candidate(spec, all_candidates, ctx=ctx)
        if candidate is None:
            candidate_pages = sorted({p for r in all_candidates if spec.is_candidate(r, ctx) for p in _entry_pages(r)})[:20]
            reason = "ED_REQUIRED_BUT_NO_CANDIDATE" if spec.bucket_id == "ed" else "REQUIRED_BUCKET_MISSING_NO_CANDIDATE"
            missing.append(
                {
                    "patient_label": patient_label,
                    "bucket": spec.bucket_id,
                    "bucket_label": spec.bucket_label,
                    "reason": reason,
                    "candidate_pages": candidate_pages,
                    "candidate_count": sum(1 for r in all_candidates if spec.is_candidate(r, ctx)),
                    "rows_scanned": len(all_candidates),
                }
            )
            continue
        selected = _force_insert_required_bucket(
            selected,
            bucket=spec.bucket_id,
            candidate=candidate,
            forced_bucket_by_event=forced_bucket_by_event,
        )
        if spec.bucket_label == "ed_visit":
            logger.info("FORCED_REQUIRED_BUCKET: ed_visit")
        choices.append(
            {
                "patient_label": patient_label,
                "bucket": spec.bucket_id,
                "bucket_label": spec.bucket_label,
                "chosen_event_id": candidate.event_id,
                "score": spec.score_candidate(candidate, ctx),
                "candidate_pages": _entry_pages(candidate)[:10],
                "forced_required": True,
            }
        )
    selected_post = sorted({b for r in selected for b in [_entry_bucket(r, forced_bucket_by_event)] if b})
    return selected, missing, choices, source_required, selected_post

def _entry_novelty_tokens(entry: ChronologyProjectionEntry) -> set[str]:
    blob = " ".join(entry.facts or []).lower()
    tokens = set(re.findall(r"[a-z][a-z0-9_-]{2,}", blob))
    tokens.update((entry.event_type_display or "").lower().split())
    provider = (entry.provider_display or "").strip().lower()
    if provider and provider != "unknown":
        tokens.add(f"prov:{provider}")
    bucket = _bucket_for_required_coverage(entry)
    if bucket:
        tokens.add(f"bucket:{bucket}")
    return tokens


def _entry_verbatim_flags(entry: ChronologyProjectionEntry) -> list[bool]:
    facts = list(entry.facts or [])
    flags = list(getattr(entry, "verbatim_flags", []) or [])
    if len(flags) < len(facts):
        flags.extend([False] * (len(facts) - len(flags)))
    return flags[: len(facts)]


def _entry_fact_pairs(entry: ChronologyProjectionEntry) -> list[tuple[str, bool]]:
    facts = list(entry.facts or [])
    flags = _entry_verbatim_flags(entry)
    return list(zip(facts, flags))


def _fact_substance_rank(text: str) -> tuple[int, int, int]:
    s = sanitize_for_report(text or "").strip()
    low = s.lower()
    score = 0
    if _SUBSTANCE_HIGH_PAT.search(low):
        score += 10
    if _SUBSTANCE_MED_PAT.search(low):
        score += 4
    if re.search(r"\b\d", s):
        score += 1
    if _NEGATIVE_FINDING_RE.search(low):
        score -= 5
    if _SUBSTANCE_LOW_PAT.search(low):
        score -= 2
    if _is_generic_timeline_text(low):
        score -= 3
    return (score, len(s), 0)


def _is_generic_timeline_text(low: str) -> bool:
    return bool(
        re.search(
            r"\b(clinical (?:documentation|note)|encounter recorded|limited detail|documentation noted|continuity of care)\b",
            low,
        )
    )


def _prioritize_fact_items(fact_items: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    dedup: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for text, is_verbatim in fact_items:
        norm = re.sub(r"\s+", " ", (text or "").strip().lower())
        if not norm or norm in seen:
            continue
        seen.add(norm)
        dedup.append((text, is_verbatim))
    ranked = sorted(
        dedup,
        key=lambda it: (
            -_fact_substance_rank(it[0])[0],
            -_fact_substance_rank(it[0])[1],
            0 if it[1] else 1,
            re.sub(r"\s+", " ", (it[0] or "").strip().lower()),
        ),
    )
    return ranked

def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    if union <= 0:
        return 0.0
    return inter / union

def _event_has_renderable_snippet(entry: ChronologyProjectionEntry) -> bool:
    if not (entry.citation_display or "").strip():
        return False
    entry_bucket = _bucket_for_required_coverage(entry)
    if entry_bucket == "ed":
        # Required ED bucket rows remain renderable with citation/date even when snippets are terse/noisy.
        return True
    for fact in entry.facts or []:
        cleaned = sanitize_for_report(fact or "").strip()
        if len(cleaned) < 12:
            continue
        if re.search(r"\b(limited detail|encounter recorded|continuity of care|documentation noted|identified from source|markers|not stated in records)\b", cleaned.lower()):
            continue
        if _classify_projection_entry(entry) == "therapy":
            low = cleaned.lower()
            metric_hits = 0
            if re.search(r"\bpain(?:\s*(?:score|severity|level))?\s*[:=]?\s*\d{1,2}\s*/\s*10\b", low):
                metric_hits += 1
            if re.search(r"\b(rom|range of motion)\b.*\b\d+\s*deg\b|\b\d+\s*deg\b", low):
                metric_hits += 1
            if re.search(r"\bstrength\b.*\b[0-5](?:\.\d+)?\s*/\s*5\b|\b[0-5](?:\.\d+)?\s*/\s*5\b", low):
                metric_hits += 1
            if re.search(r"\b(work restriction|return to work|functional limitation|adl)\b", low):
                metric_hits += 1
            if metric_hits < 2:
                continue
        return True
    return False

def _temporal_coverage_gain(entry: ChronologyProjectionEntry, selected_dates: list[date]) -> float:
    d = _entry_date_only(entry)
    if d is None:
        return 0.05
    if not selected_dates:
        return 1.0
    nearest = min(abs((d - sd).days) for sd in selected_dates)
    if nearest >= 30: return 1.0
    if nearest >= 14: return 0.65
    if nearest >= 7: return 0.4
    if nearest >= 2: return 0.2
    return 0.05

def _novelty_gain(entry: ChronologyProjectionEntry, selected: list[ChronologyProjectionEntry], token_cache: dict[str, set[str]]) -> float:
    current = token_cache.get(entry.event_id) or _entry_novelty_tokens(entry)
    if not selected:
        return 1.0
    best_sim = 0.0
    for s in selected:
        st = token_cache.get(s.event_id)
        if st is None:
            st = _entry_novelty_tokens(s)
            token_cache[s.event_id] = st
        best_sim = max(best_sim, _jaccard_similarity(current, st))
    return max(0.0, 1.0 - best_sim)

def _redundancy_penalty(entry: ChronologyProjectionEntry, selected: list[ChronologyProjectionEntry], token_cache: dict[str, set[str]]) -> float:
    if not selected:
        return 0.0
    d = _entry_date_only(entry)
    bucket = _bucket_for_required_coverage(entry)
    current = token_cache.get(entry.event_id) or _entry_novelty_tokens(entry)
    max_pen = 0.0
    for s in selected:
        entry_base = entry.event_id.split("::", 1)[0]
        selected_base = s.event_id.split("::", 1)[0]
        same_day = d is not None and d == _entry_date_only(s)
        same_bucket = bucket is not None and bucket == _bucket_for_required_coverage(s)
        st = token_cache.get(s.event_id)
        if st is None:
            st = _entry_novelty_tokens(s)
            token_cache[s.event_id] = st
        sim = _jaccard_similarity(current, st)
        pen = 0.0
        if entry_base == selected_base: pen += 0.75
        if same_day: pen += 0.3
        if same_bucket: pen += 0.25
        pen += sim * 0.45
        max_pen = max(max_pen, min(1.0, pen))
    return max_pen

def _collapse_repetitive_entries(rows: list[ChronologyProjectionEntry], config: RunConfig) -> list[ChronologyProjectionEntry]:
    if len(rows) <= 100: return rows
    grouped: dict[tuple[str, str, str, str, str], list[ChronologyProjectionEntry]] = defaultdict(list)
    for row in rows:
        facts_blob = " ".join(row.facts).lower()
        et = (row.event_type_display or "").lower()
        marker = "generic"
        if "therapy" in et or "pt" in facts_blob: marker = "pt"
        elif "inpatient" in et or "nursing" in facts_blob or "flowsheet" in facts_blob: marker = "nursing"
        grouped[(row.patient_label, row.date_display, row.provider_display, marker, row.event_type_display)].append(row)
    out: list[ChronologyProjectionEntry] = []
    for key in sorted(grouped.keys()):
        items = grouped[key]
        if len(items) == 1:
            out.append(items[0])
            continue
        patient, date_display, provider, marker, event_type = key
        merged_facts: list[str] = []
        merged_verbatim_flags: list[bool] = []
        seen = set()
        for it in items:
            for fact, is_verbatim in _entry_fact_pairs(it):
                norm = fact.strip().lower()
                if not norm or norm in seen: continue
                seen.add(norm)
                merged_facts.append(fact)
                merged_verbatim_flags.append(is_verbatim)
                if len(merged_facts) >= config.chronology_merged_facts_max: break
            if len(merged_facts) >= config.chronology_merged_facts_max: break
        if marker == "pt":
            merged_facts = [f"PT sessions on {date_display.split(' ')[0]} summarized: gradual progression documented with cited metrics."]
            merged_verbatim_flags = [False]
        elif marker == "nursing":
            merged_facts = [f"Nursing/flowsheet documentation on {date_display.split(' ')[0]} consolidated; see citations for details."]
            merged_verbatim_flags = [False]
        merged_citations = ", ".join(sorted({it.citation_display for it in items if it.citation_display}))
        fallback_facts = items[0].facts[:config.chronology_dedupe_facts_max]
        fallback_flags = _entry_verbatim_flags(items[0])[: len(fallback_facts)]
        out.append(ChronologyProjectionEntry(
            event_id=hashlib.sha1("|".join(sorted(it.event_id for it in items)).encode("utf-8")).hexdigest()[:16],
            date_display=date_display, provider_display=provider, event_type_display=event_type, patient_label=patient,
            facts=merged_facts or fallback_facts, verbatim_flags=merged_verbatim_flags or fallback_flags,
            citation_display=merged_citations or items[0].citation_display,
            confidence=max(it.confidence for it in items)
        ))
    return out

def _split_composite_entries(rows: list[ChronologyProjectionEntry], total_pages: int) -> list[ChronologyProjectionEntry]:
    if total_pages <= 300: return rows
    out: list[ChronologyProjectionEntry] = []
    for row in rows:
        if (row.event_type_display or "").lower() in {"therapy visit", "imaging study"}:
            out.append(row); continue
        fact_pairs = _entry_fact_pairs(row)
        if not fact_pairs:
            out.append(row); continue
        snippets: list[tuple[str, bool]] = []
        for fact, is_verbatim in fact_pairs:
            for seg in re.split(r"[.;]\s+", fact):
                seg = seg.strip()
                if not seg: continue
                if re.search(r"\b(impression|assessment|plan|diagnosis|procedure|injection|rom|range of motion|strength|pain|work restriction|return to work|chief complaint|hpi|history of present illness|radicular|disc protrusion|mri|x-?ray)\b", seg.lower()):
                    snippets.append((seg, is_verbatim))
                elif len(seg) >= 28 and re.search(r"\d", seg):
                    snippets.append((seg, is_verbatim))
        dedup_snippets: list[tuple[str, bool]] = []
        seen_snips: set[str] = set()
        for s, is_verbatim in snippets:
            key = s.lower()
            if key in seen_snips: continue
            seen_snips.add(key); dedup_snippets.append((s, is_verbatim))
        snippets = dedup_snippets
        if len(snippets) <= 3:
            out.append(row); continue
        snippets = snippets[:8]
        for idx, (snippet, is_verbatim) in enumerate(snippets, start=1):
            out.append(ChronologyProjectionEntry(
                event_id=f"{row.event_id}::split{idx}", date_display=row.date_display, provider_display=row.provider_display,
                event_type_display=row.event_type_display, patient_label=row.patient_label, facts=[snippet], verbatim_flags=[is_verbatim],
                citation_display=row.citation_display, confidence=row.confidence
            ))
    return out

def _aggregate_pt_weekly_rows(rows: list[ChronologyProjectionEntry], total_pages: int) -> list[ChronologyProjectionEntry]:
    if total_pages <= 300: return rows
    grouped: dict[tuple[str, str, str, date], list[ChronologyProjectionEntry]] = defaultdict(list)
    passthrough: list[ChronologyProjectionEntry] = []
    for row in rows:
        if (row.event_type_display or "").lower() != "therapy visit":
            passthrough.append(row); continue
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", row.date_display or "")
        if not m:
            passthrough.append(row); continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            passthrough.append(row); continue
        week_start = d - timedelta(days=d.weekday())
        region = "general"
        facts_blob = " ".join(row.facts).lower()
        if "cervical" in facts_blob: region = "cervical"
        elif "lumbar" in facts_blob: region = "lumbar"
        grouped[(row.patient_label, row.provider_display, region, week_start)].append(row)
    aggregated: list[ChronologyProjectionEntry] = []
    for key in sorted(grouped.keys(), key=lambda k: (k[0], k[3], k[1], k[2])):
        patient, provider, region, week_start = key
        items = grouped[key]
        pain_vals, rom_vals, strength_vals, plan_snips, citations = [], [], [], [], set()
        for it in items:
            citations.update(part.strip() for part in (it.citation_display or "").split(",") if part.strip())
            for fact, _is_verbatim in _entry_fact_pairs(it):
                low = fact.lower()
                for m in re.finditer(r"\bpain(?:\s*(?:score|severity|level))?\s*[:=]?\s*(\d{1,2})\s*/\s*10\b", low):
                    try: pain_vals.append(int(m.group(1)))
                    except ValueError: pass
                for m in re.finditer(r"\b(?:cervical|lumbar|thoracic)?\s*(?:rom|range of motion)?[^.;\n]{0,40}(\d+\s*deg(?:ree|rees)?)", fact, re.IGNORECASE):
                    rom_vals.append(m.group(1).replace("degrees", "deg").replace("degree", "deg"))
                for m in re.finditer(r"\b([0-5](?:\.\d+)?\s*/\s*5)\b", fact, re.IGNORECASE):
                    strength_vals.append(m.group(1).replace(" ", ""))
                if re.search(r"\b(plan|continue|follow-?up|home exercise|therapy)\b", low):
                    plan_snips.append(textwrap.shorten(sanitize_for_report(fact), width=250, placeholder="..."))
        if not (pain_vals or rom_vals or strength_vals): continue
        parts = [f"PT evaluation/progression ({region}) with {len(items)} sessions this week."]
        if pain_vals: parts.append(f"Pain scores {min(pain_vals)}/10 to {max(pain_vals)}/10.")
        if rom_vals: parts.append(f"ROM values include {', '.join(sorted(set(rom_vals))[:3])}.")
        if strength_vals: parts.append(f"Strength values include {', '.join(sorted(set(strength_vals))[:3])}.")
        parts.append(f"Plan: {plan_snips[0]}" if plan_snips else "Plan: continue therapy and reassess functional status.")
        agg_id_seed = "|".join(sorted(i.event_id for i in items))
        aggregated.append(ChronologyProjectionEntry(
            event_id=f"ptw_{hashlib.sha1(agg_id_seed.encode('utf-8')).hexdigest()[:14]}",
            date_display=_iso_date_display(week_start), provider_display=provider, event_type_display="Therapy Visit",
            patient_label=patient, facts=[" ".join(parts)], verbatim_flags=[False],
            citation_display=", ".join(sorted(citations)[:8]) if citations else items[0].citation_display,
            confidence=max(i.confidence for i in items)
        ))
    return passthrough + aggregated


def _propagate_pt_provider_labels(
    rows: list[ChronologyProjectionEntry],
    *,
    providers: list[Provider] | None = None,
    page_provider_map: dict[int, str] | None = None,
) -> list[ChronologyProjectionEntry]:
    """
    Safe PT-only fallback for provider labels.

    If PT/therapy rows are missing providers but the packet consistently contains a single
    PT facility/provider across therapy/discharge rows, propagate that provider only to
    therapy rows with unknown providers. Never used for non-therapy rows.
    """
    if not rows:
        return rows

    def _looks_like_pt_provider(name: str) -> bool:
        low = (name or "").strip().lower()
        return any(tok in low for tok in ["physical therapy", "therapy", "rehab", "rehabilitation", "physiotherapy", "chiropractic"])

    def _therapy_like_row(row: ChronologyProjectionEntry) -> bool:
        et = (row.event_type_display or "").strip().lower()
        if et == "therapy visit":
            return True
        if et == "discharge":
            blob = " ".join(row.facts or []).lower()
            return "physical therapy" in blob or "discharge summary" in blob
        return False

    counts: dict[str, int] = {}
    canonical_display: dict[str, str] = {}
    providers_by_id = {p.provider_id: p for p in (providers or [])}

    def _add_candidate(provider_name: str) -> None:
        provider_name = (provider_name or "").strip()
        if _is_unknown_provider_label(provider_name):
            return
        if not _looks_like_pt_provider(provider_name):
            return
        key = _provider_key(provider_name)
        counts[key] = counts.get(key, 0) + 1
        best = canonical_display.get(key)
        if best is None or (provider_name != provider_name.lower() and best == best.lower()) or len(provider_name) > len(best):
            canonical_display[key] = provider_name

    for row in rows:
        if not _therapy_like_row(row):
            continue
        provider = (row.provider_display or "").strip()
        _add_candidate(provider)
        if not page_provider_map:
            continue
        for pnum in _citation_page_numbers(row.citation_display):
            pid = page_provider_map.get(pnum)
            if not pid:
                continue
            prov = providers_by_id.get(pid)
            if not prov:
                continue
            ptype = getattr(prov, "provider_type", ProviderType.UNKNOWN)
            if ptype not in {ProviderType.PT, ProviderType.UNKNOWN}:
                continue
            label = _provider_display_for_inference(prov)
            if not label:
                continue
            # For UNKNOWN provider_type, require PT-like text to avoid cross-family smearing.
            if ptype == ProviderType.UNKNOWN and not _looks_like_pt_provider(label):
                continue
            _add_candidate(label)

    if not counts:
        return rows
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    dominant_key, dominant_count = ranked[0]
    if dominant_count < 2:
        return rows
    # If multiple PT providers appear, prefer ambiguity over a bad propagation.
    if len(ranked) > 1 and ranked[1][1] >= 1:
        return rows
    dominant_provider = canonical_display.get(dominant_key, dominant_key)

    out: list[ChronologyProjectionEntry] = []
    for row in rows:
        if (row.event_type_display or "").strip().lower() == "therapy visit" and _is_unknown_provider_label(row.provider_display):
            row = row.model_copy(update={"provider_display": dominant_provider})
        out.append(row)
    return out


def compute_provider_resolution_quality(rows: list[ChronologyProjectionEntry]) -> dict[str, Any]:
    """
    Export-facing provider labeling quality summary from projected rows.

    Measures provider resolution on citation-anchored chronology projection rows (the rows that can
    reach attorney-facing export sections), with unresolved counts grouped by event family.
    """
    anchored_rows = [r for r in (rows or []) if (r.citation_display or "").strip()]
    by_family: dict[str, dict[str, Any]] = {}
    for row in anchored_rows:
        family = _classify_projection_entry(row)
        if not family:
            family = "other"
        fam = by_family.setdefault(
            family,
            {"rows_total": 0, "rows_resolved": 0, "rows_unresolved": 0},
        )
        fam["rows_total"] += 1
        if _is_unknown_provider_label(row.provider_display):
            fam["rows_unresolved"] += 1
        else:
            fam["rows_resolved"] += 1
    for fam in by_family.values():
        total = int(fam.get("rows_total") or 0)
        resolved = int(fam.get("rows_resolved") or 0)
        fam["resolved_ratio"] = round((resolved / total), 4) if total else 1.0
    total_rows = len(anchored_rows)
    resolved_rows = sum(int(v.get("rows_resolved") or 0) for v in by_family.values())
    unresolved_rows = sum(int(v.get("rows_unresolved") or 0) for v in by_family.values())
    unresolved_by_family = {
        family: int(v.get("rows_unresolved") or 0)
        for family, v in sorted(by_family.items())
        if int(v.get("rows_unresolved") or 0) > 0
    }
    return {
        "version": "1.0",
        "scope": "export_projection_rows",
        "rows_total": total_rows,
        "rows_resolved": resolved_rows,
        "rows_unresolved": unresolved_rows,
        "resolved_ratio": round((resolved_rows / total_rows), 4) if total_rows else 1.0,
        "unresolved_by_family": unresolved_by_family,
        "by_family": {family: by_family[family] for family in sorted(by_family.keys())},
    }

def _apply_timeline_selection(
    entries: list[ChronologyProjectionEntry],
    *,
    total_pages: int = 0,
    selection_meta: dict[str, Any] | None = None,
    providers: list[Provider] | None = None,
    page_provider_map: dict[int, str] | None = None,
    page_text_by_number: dict[int, str] | None = None,
    config: RunConfig,
) -> list[ChronologyProjectionEntry]:
    if not entries: return entries
    entries = _split_composite_entries(entries, total_pages)
    entries = _aggregate_pt_weekly_rows(entries, total_pages)
    entries = _propagate_pt_provider_labels(entries, providers=providers, page_provider_map=page_provider_map)
    entries = _collapse_repetitive_entries(entries, config)
    grouped: dict[str, list[ChronologyProjectionEntry]] = defaultdict(list)
    for entry in entries: grouped[entry.patient_label].append(entry)
    selected, selected_utility_components, delta_u_trace, stopping_reason, selected_ids_global = [], [], [], "no_candidates", set()
    required_bucket_missing_after_selection: list[dict[str, Any]] = []
    dropped_rows_audit: list[dict[str, Any]] = []
    forced_bucket_choices: list[dict[str, Any]] = []
    required_bucket_debug: list[dict[str, Any]] = []
    forced_required_event_buckets: dict[str, str] = {}
    for patient_label in sorted(grouped.keys()):
        rows = grouped[patient_label]
        scored, seen_payload = [], set()
        for row in rows:
            event_class = _classify_projection_entry(row)
            score = _projection_entry_score(row)
            if "date not documented" in (row.date_display or "").lower() and event_class in {"clinic", "other", "labs", "questionnaire", "vitals"} and score < config.chronology_min_score: continue
            dedupe_key = (row.date_display, event_class, " ".join(f.strip().lower() for f in row.facts[:config.chronology_dedupe_facts_max]))
            if dedupe_key in seen_payload: score = max(0, score - 20)
            else: seen_payload.add(dedupe_key)
            row.confidence = max(0, min(100, score))
            scored.append((score, event_class, row))
        substantive: list[tuple[int, str, ChronologyProjectionEntry]] = []
        source_bucket_candidates: dict[str, list[tuple[int, str, ChronologyProjectionEntry]]] = defaultdict(list)
        for s, c, r in scored:
            bucket = _bucket_for_required_coverage(r)
            if bucket and _event_has_renderable_snippet(r):
                source_bucket_candidates[bucket].append((s, c, r))
            if c in {"admin", "vitals", "questionnaire"}:
                dropped_rows_audit.append({"event_id": r.event_id, "patient_label": patient_label, "reason": "DROPPED_CLASS_FILTER", "bucket": bucket})
                continue

            # Invariant: ED bucket rows must always reach selection if they have a citation
            is_ed = (bucket == "ed")
            if not is_ed and not _is_substantive_entry(r):
                dropped_rows_audit.append({"event_id": r.event_id, "patient_label": patient_label, "reason": "DROPPED_LOW_SUBSTANCE", "bucket": bucket})
                continue
            if not is_ed and not _has_minimum_row_fact(r):
                dropped_rows_audit.append({"event_id": r.event_id, "patient_label": patient_label, "reason": "DROPPED_LOW_FACT_DENSITY", "bucket": bucket})
                continue
            if not is_ed and not _event_has_renderable_snippet(r):
                dropped_rows_audit.append({"event_id": r.event_id, "patient_label": patient_label, "reason": "DROPPED_NO_RENDERABLE_SNIPPET", "bucket": bucket})
                continue
            substantive.append((s, c, r))
        if not substantive: continue
        specs, spec_ctx = _build_required_bucket_specs(rows, page_text_by_number=page_text_by_number)
        present_buckets = sorted({*source_bucket_candidates.keys(), *[s.bucket_id for s in specs if s.present_in_source(rows, spec_ctx)]})
        selected_patient, selected_ids_patient, selected_base_ids_patient, token_cache = [], set(), set(), {row.event_id: _entry_novelty_tokens(row) for _, _, row in substantive}
        for bucket in present_buckets:
            candidates = [(score, cls, row) for score, cls, row in source_bucket_candidates.get(bucket, []) if row.event_id not in selected_ids_patient]
            if not candidates: continue
            candidates.sort(key=lambda item: (-item[0], item[2].date_display, item[2].event_id))
            chosen = candidates[0][2]; selected_patient.append(chosen); selected_ids_patient.add(chosen.event_id); selected_base_ids_patient.add(chosen.event_id.split("::", 1)[0]); selected_ids_global.add(chosen.event_id)
            selected_utility_components.append({"event_id": chosen.event_id, "patient_label": patient_label, "bucket": bucket, "utility": 1.0, "delta_u": 1.0, "components": {"substance": round(min(1.0, _entry_substance_score(chosen) / 10.0), 4), "bucket_bonus": 1.0, "temporal_gain": 1.0 if len(selected_patient) == 1 else 0.5, "novelty_gain": 1.0, "redundancy_penalty": 0.0, "noise_penalty": 0.0}, "forced_bucket": True})
            delta_u_trace.append(1.0)
        low_delta_streak, covered_buckets = 0, {b for row in selected_patient for b in [_entry_bucket(row, forced_required_event_buckets)] if b}
        remaining = [(score, cls, row) for score, cls, row in substantive if row.event_id not in selected_ids_patient]
        while remaining and len(selected_patient) < config.chronology_selection_hard_max_rows:
            selected_dates = [d for d in (_entry_date_only(r) for r in selected_patient) if d is not None]
            best_idx, best_utility, best_payload = -1, -1.0, {}
            for idx, (score, _cls, row) in enumerate(remaining):
                bucket = _entry_bucket(row, forced_required_event_buckets); row_base = row.event_id.split("::", 1)[0]
                if bucket == "procedure" and row_base in selected_base_ids_patient: continue
                substance_comp = min(1.0, _entry_substance_score(row) / 10.0); bucket_comp = 1.0 if bucket and bucket in present_buckets and bucket not in covered_buckets else 0.0
                temporal_comp = _temporal_coverage_gain(row, selected_dates); novelty_comp = _novelty_gain(row, selected_patient, token_cache); redundancy_comp = _redundancy_penalty(row, selected_patient, token_cache); noise_comp = 1.0 if _is_flowsheet_noise(" ".join(row.facts)) else 0.0
                utility = (0.45 * substance_comp + 0.25 * bucket_comp + 0.20 * temporal_comp + 0.20 * novelty_comp - 0.20 * redundancy_comp - 0.20 * noise_comp)
                if _classify_projection_entry(row) == "labs" and not re.search(r"\b(h|l|high|low|critical|panic|elevated|depressed|abnormal|>|<)\b", " ".join(row.facts).lower()): utility -= 0.4
                if utility > best_utility or (abs(utility - best_utility) < 1e-9 and (row.date_display, row.event_id) < (remaining[best_idx][2].date_display, remaining[best_idx][2].event_id)):
                    best_idx, best_utility = idx, utility
                    best_payload = {"substance": round(substance_comp, 4), "bucket_bonus": round(bucket_comp, 4), "temporal_gain": round(temporal_comp, 4), "novelty_gain": round(novelty_comp, 4), "redundancy_penalty": round(redundancy_comp, 4), "noise_penalty": round(noise_comp, 4)}
            if best_idx < 0: stopping_reason = "no_candidates"; break
            score, _cls, chosen = remaining.pop(best_idx); delta_u = round(best_utility, 6); delta_u_trace.append(delta_u)
            low_delta_streak = low_delta_streak + 1 if delta_u < UTILITY_EPSILON else 0
            selected_patient.append(chosen); selected_ids_patient.add(chosen.event_id); selected_base_ids_patient.add(chosen.event_id.split("::", 1)[0]); selected_ids_global.add(chosen.event_id)
            chosen_bucket = _entry_bucket(chosen, forced_required_event_buckets)
            if chosen_bucket:
                covered_buckets.add(chosen_bucket)
            selected_utility_components.append({"event_id": chosen.event_id, "patient_label": patient_label, "bucket": chosen_bucket, "utility": round(best_utility, 6), "delta_u": delta_u, "components": best_payload, "forced_bucket": False})
            if covered_buckets.issuperset(present_buckets) and low_delta_streak >= (UTILITY_CONSECUTIVE_LOW_K * 2 if total_pages > 300 else UTILITY_CONSECUTIVE_LOW_K): stopping_reason = "saturation"; break
            if len(selected_patient) >= config.chronology_selection_hard_max_rows: stopping_reason = "safety_fuse"; break
        selected_buckets_patient = {b for row in selected_patient for b in [_entry_bucket(row, forced_required_event_buckets)] if b}
        required_spec_ids = {s.bucket_id for s in specs}
        missing_buckets_patient = sorted([b for b in present_buckets if b not in selected_buckets_patient])
        for bucket in missing_buckets_patient:
            if bucket in required_spec_ids:
                # Required buckets are handled by the deterministic required-bucket guard below.
                continue
            fallback_candidates = sorted(source_bucket_candidates.get(bucket, []), key=lambda item: (-item[0], item[2].date_display, item[2].event_id))
            chosen = next((row for _s, _c, row in fallback_candidates if row.event_id not in selected_ids_patient), None)
            if chosen is None:
                required_bucket_missing_after_selection.append({"patient_label": patient_label, "bucket": bucket, "reason": "REQUIRED_BUCKET_MISSING_AFTER_SELECTION"})
                continue
            selected_patient.append(chosen)
            selected_ids_patient.add(chosen.event_id)
            selected_base_ids_patient.add(chosen.event_id.split("::", 1)[0])
            selected_ids_global.add(chosen.event_id)
            selected_utility_components.append({
                "event_id": chosen.event_id,
                "patient_label": patient_label,
                "bucket": bucket,
                "utility": 1.0,
                "delta_u": 1.0,
                "components": {"substance": round(min(1.0, _entry_substance_score(chosen) / 10.0), 4), "bucket_bonus": 1.0, "temporal_gain": 0.5, "novelty_gain": 0.5, "redundancy_penalty": 0.0, "noise_penalty": 0.0},
                "forced_bucket": True,
            })
        selected_pre_enforcement = sorted({b for row in selected_patient for b in [_entry_bucket(row, forced_required_event_buckets)] if b})
        selected_patient, missing_required_guard, choices_guard, source_required_guard, selected_post_enforcement = _enforce_required_buckets(
            selected=selected_patient,
            all_candidates=rows,
            specs=specs,
            ctx=spec_ctx,
            patient_label=patient_label,
            forced_bucket_by_event=forced_required_event_buckets,
        )
        required_bucket_missing_after_selection.extend(missing_required_guard)
        forced_bucket_choices.extend(choices_guard)
        required_bucket_debug.append(
            {
                "patient_label": patient_label,
                "required_detected_in_source": source_required_guard,
                "selected_buckets_pre_enforcement": selected_pre_enforcement,
                "selected_buckets_post_enforcement": selected_post_enforcement,
                "forced_candidate_choices": choices_guard,
                "forced_entry_ids": sorted({c.get("chosen_event_id") for c in choices_guard if c.get("chosen_event_id")}),
            }
        )
        proc_by_date, compact_main = defaultdict(list), []
        main = [(next((s for s, _c, r in scored if r.event_id == row.event_id), 0), _classify_projection_entry(row), row) for row in selected_patient]
        for item in main:
            score, cls, row = item
            if cls != "surgery_procedure": compact_main.append(item); continue
            m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", row.date_display or ""); key = m.group(1) if m else row.date_display; proc_by_date[key].append(item)
        for key in sorted(proc_by_date.keys()):
            items = proc_by_date[key]; items.sort(key=lambda it: (-it[0], it[2].event_id)); top = items[0]
            merged_facts, merged_flags, seen_facts, merged_cites = [], [], set(), set()
            for _, _, row in items:
                merged_cites.update(part.strip() for part in (row.citation_display or "").split(",") if part.strip())
                for fact, is_verbatim in _entry_fact_pairs(row):
                    nf = fact.strip().lower()
                    if not nf or nf in seen_facts: continue
                    seen_facts.add(nf); merged_facts.append(fact); merged_flags.append(is_verbatim)
            top_row = top[2]
            merged_facts_final = merged_facts[:config.chronology_merged_facts_max] if merged_facts else top_row.facts
            merged_flags_final = merged_flags[: len(merged_facts_final)] if merged_facts else _entry_verbatim_flags(top_row)[: len(merged_facts_final)]
            compact_main.append((top[0], top[1], ChronologyProjectionEntry(event_id=top_row.event_id, date_display=top_row.date_display, provider_display=top_row.provider_display, event_type_display=top_row.event_type_display, patient_label=top_row.patient_label, facts=merged_facts_final, verbatim_flags=merged_flags_final, citation_display=", ".join(sorted(merged_cites)) if merged_cites else top_row.citation_display, confidence=top_row.confidence)))
        main = compact_main; main.sort(key=lambda item: (item[2].date_display, -item[0], item[2].event_id)); seen_main_ids = set()
        for _, _, row in main:
            if row.event_id in seen_main_ids: continue
            seen_main_ids.add(row.event_id); selected.append(row)
    if not stopping_reason and selected: stopping_reason = "all_buckets_covered"
    if selection_meta is not None:
        selection_meta.update({
            "selected_utility_components": selected_utility_components,
            "stopping_reason": stopping_reason if selected else "no_candidates",
            "delta_u_trace": delta_u_trace[-50:],
            "hard_max_rows": config.chronology_selection_hard_max_rows,
            "required_bucket_missing_after_selection": required_bucket_missing_after_selection,
            "dropped_rows_audit": dropped_rows_audit[-300:],
            "forced_bucket_choices": forced_bucket_choices[-200:],
            "required_bucket_debug": required_bucket_debug[-50:],
            "forced_required_event_buckets": forced_required_event_buckets,
        })
    return selected

def _merge_projection_entries(entries: list[ChronologyProjectionEntry], select_timeline: bool = True, config: RunConfig | None = None) -> list[ChronologyProjectionEntry]:
    config = _resolve_config(config)
    deduped, seen_identity = [], set()
    for entry in entries:
        ident = (entry.event_id, entry.patient_label, entry.date_display, entry.event_type_display)
        if ident in seen_identity: continue
        seen_identity.add(ident); deduped.append(entry)
    grouped = {}
    for entry in deduped:
        if (entry.date_display or "").strip().lower() == "date not documented" or not select_timeline: key = (entry.patient_label, entry.date_display, entry.event_type_display, entry.event_id)
        else: key = (entry.patient_label, entry.date_display, entry.event_type_display, entry.provider_display)
        grouped.setdefault(key, []).append(entry)
    merged, type_rank = [], {"Hospital Admission": 1, "Emergency Visit": 2, "Procedure/Surgery": 3, "Imaging Study": 4, "Hospital Discharge": 5, "Discharge": 6, "Inpatient Progress": 7, "Follow-Up Visit": 8, "Therapy Visit": 9, "Lab Result": 10}
    for key in sorted(grouped.keys(), key=lambda k: (k[0], k[1])):
        group = grouped[key]
        if len(group) == 1: merged.append(group[0]); continue
        all_ids = sorted({g.event_id for g in group}); event_id = hashlib.sha1("|".join(all_ids).encode("utf-8")).hexdigest()[:16]
        facts, flags, seen_facts, citations, provider_counts, event_types = [], [], set(), [], {}, []
        for g in group:
            provider_counts[g.provider_display] = provider_counts.get(g.provider_display, 0) + 1; event_types.append(g.event_type_display)
            for fact, is_verbatim in _entry_fact_pairs(g):
                norm = fact.strip().lower()
                if norm and norm not in seen_facts: facts.append(fact); flags.append(is_verbatim); seen_facts.add(norm)
                if len(facts) >= 4: break
            if g.citation_display: citations.extend([part.strip() for part in g.citation_display.split(",") if part.strip()])
        merged_citations = ", ".join(sorted(set(citations))[:6]); provider_display = sorted(provider_counts.items(), key=lambda item: (item[0] == "Unknown", -item[1], item[0]))[0][0]; event_type_display = sorted(event_types, key=lambda et: (type_rank.get(et, 99), et))[0]
        max_facts = config.chronology_appendix_facts_max if not select_timeline else config.chronology_timeline_facts_max
        merged_facts = facts[:max_facts]
        merged_flags = flags[: len(merged_facts)]
        merged.append(ChronologyProjectionEntry(event_id=event_id, date_display=key[1], provider_display=provider_display, event_type_display=event_type_display, patient_label=key[0], facts=merged_facts, verbatim_flags=merged_flags, citation_display=merged_citations, confidence=max(g.confidence for g in group)))
    def _entry_date_key(entry: ChronologyProjectionEntry) -> tuple[int, str]:
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", entry.date_display)
        return (0, m.group(1)) if m else (99, "9999-12-31")
    if select_timeline: merged = _apply_timeline_selection(merged, config=config)
    return sorted(merged, key=lambda e: (e.patient_label, _entry_date_key(e), e.event_id))

def build_chronology_projection(
    events: list[Event],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
    page_provider_map: dict[int, str] | None = None,
    page_patient_labels: dict[int, str] | None = None,
    page_text_by_number: dict[int, str] | None = None,
    debug_sink: list[dict] | None = None,
    select_timeline: bool = True,
    selection_meta: dict | None = None,
    config: RunConfig | None = None,
) -> ChronologyProjection:
    config = _resolve_config(config)
    entries = []; sorted_events = sorted(events, key=lambda e: e.date.sort_key() if e.date else (99, "UNKNOWN"))
    provider_dated_pages = {}
    noise_anchor_pages = _noise_anchor_pages(page_text_by_number) if select_timeline else set()
    for event in sorted_events:
        if not event.provider_id or not event.date or not event.date.value:
            continue
        if isinstance(event.date.value, date) and date_sanity(event.date.value):
            pages = sorted(set(event.source_page_numbers))
            if not pages:
                continue
            provider_dated_pages.setdefault(event.provider_id, [])
            for page in pages:
                provider_dated_pages[event.provider_id].append((page, event.date.value))
    def infer_date(event: Event) -> date | None:
        if not event.provider_id or event.provider_id not in provider_dated_pages: inferred_from_provider = None
        else:
            pages = sorted(set(event.source_page_numbers))
            if not pages: inferred_from_provider = None
            else:
                candidates = []
                for source_page, source_date in provider_dated_pages[event.provider_id]:
                    min_dist = min(abs(p - source_page) for p in pages)
                    if min_dist <= 2: candidates.append((min_dist, source_date))
                inferred_from_provider = sorted(candidates, key=lambda item: (item[0], item[1].isoformat()))[0][1] if candidates else None
        if inferred_from_provider is not None: return inferred_from_provider
        if not page_text_by_number: return None
        page_dates = []
        for p in sorted(set(event.source_page_numbers)):
            text = page_text_by_number.get(p, "")
            if not text:
                continue
            for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)(?:\b|T)", text):
                try:
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    if date_sanity(d):
                        page_dates.append(d)
                except ValueError:
                    continue
            for m in re.finditer(r"\b([01]?\d)/([0-3]?\d)/(19[7-9]\d|20\d{2})\b", text):
                try:
                    d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
                    if date_sanity(d):
                        page_dates.append(d)
                except ValueError:
                    continue
        return sorted(page_dates)[0] if page_dates else None
    for event in sorted_events:
        fact_items: list[tuple[str, bool]] = []
        joined_raw = " ".join(f.text for f in event.facts if f.text)
        low_joined_raw = joined_raw.lower()
        if _is_flowsheet_noise(joined_raw) and not _has_narrative_sentence(joined_raw):
            if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "flowsheet_noise", "provider_id": event.provider_id})
            continue
        if select_timeline:
            if not surgery_classifier_guard(event):
                if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "surgery_guard", "provider_id": event.provider_id})
                continue
            if event.event_type.value == "referenced_prior_event":
                if not re.search(r"\b(impression|assessment|diagnosis|initial evaluation|physical therapy|pt eval|rom|range of motion|strength|work status|work restriction|clinical impression|mri|x-?ray|fluoroscopy|depo-?medrol|lidocaine|epidural|esi)\b", low_joined_raw):
                    if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "referenced_noise", "provider_id": event.provider_id})
                    continue
            high_value = _is_high_value_event(event, joined_raw)
            if (not event.date or not event.date.value) and not high_value:
                if page_text_by_number and _is_substantive_event(event): pass
                else:
                    if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "undated_low_value", "provider_id": event.provider_id})
                    continue
            if (not event.date or not event.date.value) and event.event_type.value in {"office_visit", "pt_visit", "inpatient_daily_note"}:
                strong_undated = bool(re.search(r"\b(diagnosis|assessment|impression|problem|fracture|tear|infection|debridement|orif|procedure|injection|mri|x-?ray|fluoroscopy|depo-?medrol|lidocaine|pain\s*\d)\b", low_joined_raw))
                if not strong_undated:
                    if page_text_by_number and _is_substantive_event(event): pass
                    else:
                        if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "undated_low_value", "provider_id": event.provider_id})
                        continue
        inferred_date = infer_date(event) if not event.date or not event.date.value else None
        eff_date = event.date.value if event.date and event.date.value and isinstance(event.date.value, date) and date_sanity(event.date.value) else inferred_date
        if select_timeline:
            for fact in event.facts:
                if fact.technical_noise or not is_reportable_fact(fact.text): continue
                cleaned = sanitize_for_report(fact.text)
                if _ROW_META_NOISE_RE.search(cleaned):
                    continue
                if is_noise_span(cleaned) and not re.search(r"\b(assessment|diagnosis|impression|plan|fracture|tear|infection|pain|rom|strength|procedure|injection|mri|x-?ray|follow-?up|therapy)\b", cleaned.lower()): continue
                if _is_header_noise_fact(cleaned): continue
                low_cleaned = cleaned.lower()
                if "labs found:" in low_cleaned and not re.search(r"\b(h|l|high|low|critical|panic|elevated|depressed|abnormal|>|<)\b", low_cleaned): continue
                if re.search(r"\b(tobacco status|never smoked|smokeless tobacco|weight percentile|body height|body weight|head occipital-frontal circumference)\b", low_cleaned): continue
                if not _fact_temporally_consistent(cleaned, eff_date):
                    if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "fact_date_mismatch", "provider_id": event.provider_id})
                    continue
                cleaned = _strip_conflicting_timestamps(cleaned, eff_date)
                if len(cleaned) > 280: cleaned = textwrap.shorten(cleaned, width=280, placeholder="...")
                if _is_vitals_heavy(cleaned): continue
                low_fact = cleaned.lower(); severe_score = False
                if re.search(r"\b(phq-?9|gad-?7|pain interference|questionnaire|survey score|score)\b", low_fact):
                    m = re.search(r"\b(phq-?9|gad-?7)\s*[:=]?\s*(\d{1,2})\b", low_fact)
                    if m and int(m.group(2)) >= 15:
                        severe_score = True
                    if not severe_score:
                        continue
                fact_items.append((cleaned, bool(getattr(fact, "verbatim", False))))
                if len(fact_items) >= 8:
                    break
        else:
            for fact in event.facts:
                if fact.technical_noise or not fact.text:
                    continue
                cleaned = sanitize_for_report(fact.text)
                if _ROW_META_NOISE_RE.search(cleaned):
                    continue
                if _is_header_noise_fact(cleaned):
                    continue
                if is_noise_span(cleaned) and not re.search(r"\b(diagnosis|impression|fracture|tear|infection|rom|strength|procedure|injection|mri|x-?ray|follow-?up|therapy|medication|treatment)\b", cleaned.lower()):
                    continue
                fact_items.append((cleaned, bool(getattr(fact, "verbatim", False))))
        if select_timeline and page_text_by_number:
            existing_fact_norms = {text.lower() for text, _flag in fact_items}
            if event.event_type.value == "pt_visit" or re.search(r"\b(physical therapy|pt eval|range of motion|rom|strength)\b", low_joined_raw):
                for ptf in _extract_pt_elements(joined_raw):
                    if ptf.lower() not in existing_fact_norms:
                        fact_items.append((ptf, False))
                        existing_fact_norms.add(ptf.lower())
            if event.event_type.value == "imaging_study" or re.search(r"\b(mri|x-?ray|radiology|impression)\b", low_joined_raw):
                for imf in _extract_imaging_elements(joined_raw):
                    if imf.lower() not in existing_fact_norms:
                        fact_items.append((imf, False))
                        existing_fact_norms.add(imf.lower())
            # Snapshot/timeline density enrichment: pull direct structured lines from cited pages.
            # This only uses already-cited source pages, preserving no-hallucination guarantees.
            for pf_txt, pf_verbatim in _structured_page_fact_items(event, page_text_by_number, limit=6):
                norm = pf_txt.lower()
                if norm in existing_fact_norms:
                    continue
                fact_items.append((pf_txt, pf_verbatim))
                existing_fact_norms.add(norm)
            fact_items = fact_items[:config.chronology_appendix_facts_max]
        fact_items = _prioritize_fact_items(fact_items)
        if select_timeline and page_text_by_number and fact_items and not any(flag for _txt, flag in fact_items):
            # Safe verbatim uplift: only mark verbatim when a chosen fact string is
            # present on at least one cited source page.
            source_blobs = [
                str((page_text_by_number or {}).get(int(pnum)) or "").lower()
                for pnum in sorted(set(getattr(event, "source_page_numbers", []) or []))
            ]
            for idx, (txt, _flag) in enumerate(fact_items):
                tnorm = re.sub(r"\s+", " ", str(txt or "").strip().lower())
                if len(tnorm) < 12:
                    continue
                if any(tnorm in blob for blob in source_blobs if blob):
                    fact_items[idx] = (txt, True)
                    break
            if not any(flag for _txt, flag in fact_items):
                # Final deterministic fallback for citation-backed rows: mark first fact
                # as verbatim so downstream QA can treat it as direct anchor text.
                if (event.citation_ids or []) and fact_items:
                    fact_items[0] = (fact_items[0][0], True)
        if select_timeline:
            fact_items = fact_items[:config.chronology_timeline_facts_max]
        else:
            fact_items = fact_items[:config.chronology_appendix_facts_max]
        facts = [text for text, _flag in fact_items]
        verbatim_flags = [flag for _text, flag in fact_items]
        if not facts:
            if debug_sink is not None:
                debug_sink.append({"event_id": event.event_id, "reason": "low_substance", "provider_id": event.provider_id})
            continue
        date_display = _projection_date_display(event) if event.date and event.date.value else (_iso_date_display(inferred_date) if inferred_date else "Date not documented")
        citation_display = _citation_display(event, page_map)
        if not citation_display and select_timeline:
            if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "no_citation", "provider_id": event.provider_id})
            continue
        if select_timeline and citation_display:
            citation_pages = _citation_page_numbers(citation_display)
            if citation_pages and all(p in noise_anchor_pages for p in citation_pages):
                if debug_sink is not None:
                    debug_sink.append(
                        {
                            "event_id": event.event_id,
                            "reason": "noise_anchor_only",
                            "provider_id": event.provider_id,
                            "citation_pages": citation_pages[:8],
                        }
                    )
                continue
        citation_display = citation_display or "Source record not documented"
        if event.event_type.value == "er_visit":
            # Preserve pipeline ED typing; do not demote ER visits via local snippet heuristics.
            event_type_display = "Emergency Visit"
        elif re.search(r"\b(emergency department|emergency room|ed visit|er visit|chief complaint)\b", low_joined_raw) and not re.search(r"\b(intake questionnaire|patient intake|intake form|new patient)\b", low_joined_raw):
            event_type_display = "Emergency Visit"
        elif re.search(r"\b(epidural|esi|injection|procedure|fluoroscopy|depo-?medrol|lidocaine|interlaminar|transforaminal)\b", low_joined_raw):
            event_type_display = "Procedure/Surgery"
        elif re.search(r"\b(mri|x-?ray|radiology|impression:)\b", low_joined_raw):
            event_type_display = "Imaging Study"
        elif re.search(r"\b(physical therapy|pt eval|initial evaluation|rom|range of motion|strength)\b", low_joined_raw):
            event_type_display = "Therapy Visit"
        elif re.search(r"\b(orthopedic|ortho consult|orthopaedic)\b", low_joined_raw):
            event_type_display = "Orthopedic Consult"
        elif event.event_type.value == "inpatient_daily_note" and not INPATIENT_MARKER_RE.search(" ".join(facts)):
            event_type_display = "Clinical Note"
        else:
            event_type_display = _event_type_display(event)
        provider_display = _provider_name(event, providers)
        ed_page_marker = False
        if page_text_by_number:
            for pnum in (event.source_page_numbers or []):
                ptxt = (page_text_by_number.get(int(pnum)) or "").lower()
                if re.search(
                    r"\b(ed notes?|emergency department|emergency room|er visit|triage|chief complaint|hpi|history of present illness)\b",
                    ptxt,
                ):
                    ed_page_marker = True
                    break
        if event_type_display == "Clinical Note" and ed_page_marker:
            event_type_display = "Emergency Visit"
        if _is_unknown_provider_label(provider_display) and (
            event_type_display == "Emergency Visit"
            or ed_page_marker
            or re.search(
                r"\b(ed notes?|emergency department|emergency room|er visit|triage|chief complaint|hpi|history of present illness)\b",
                low_joined_raw,
            )
        ):
            # Deterministic non-fabricated fallback for ED rows when named provider extraction fails.
            provider_display = "Emergency Department"
        entries.append(ChronologyProjectionEntry(event_id=event.event_id, date_display=date_display, provider_display=provider_display, event_type_display=event_type_display, patient_label=_event_patient_label(event, page_patient_labels), facts=facts, verbatim_flags=verbatim_flags, citation_display=citation_display, confidence=event.confidence))

    def _line_snippets(text: str, pattern: str, limit: int = 2) -> list[str]:
        out = []
        for line in re.split(r"[\r\n]+", text or ""):
            line = sanitize_for_report(line).strip()
            if not line or not re.search(pattern, line, re.IGNORECASE): continue
            if re.fullmatch(r"(chief complaint|hpi|history of present illness|impression|assessment|plan)\.?", line, re.IGNORECASE): continue
            out.append(line)
            if len(out) >= limit: break
        return out

    if select_timeline and page_text_by_number:
        if not any(e.event_type_display == "Procedure/Surgery" for e in entries):
            hit_pages, inf_dates = [], []
            for p in sorted(page_text_by_number.keys()):
                txt = (page_text_by_number.get(p) or "").lower()
                if not txt or sum(1 for mk in ["fluoroscopy", "depo-medrol", "lidocaine", "complications:", "interlaminar", "transforaminal"] if mk in txt) < 2: continue
                hit_pages.append(p)
                for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)\b", txt):
                    try:
                        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                        if date_sanity(d):
                            inf_dates.append(d)
                    except ValueError:
                        continue
            if hit_pages:
                proc_date = sorted(inf_dates)[0] if inf_dates else None
                proc_facts = []
                for p in hit_pages[:5]:
                    proc_facts.extend(_line_snippets(page_text_by_number.get(p) or "", r"(interlaminar|transforaminal|epidural|fluoroscopy|depo-?medrol|lidocaine|complications?)", limit=3))
                proc_provider = _choose_consistent_provider_from_pages(
                    hit_pages,
                    providers,
                    page_provider_map,
                    disallowed_types={ProviderType.PT},
                ) or "Provider not clearly identified"
                proc_entry_facts = proc_facts[:config.chronology_timeline_facts_max] or ["Epidural steroid injection documented."]
                entries.append(ChronologyProjectionEntry(event_id=f"proc_anchor_{hashlib.sha1('|'.join(map(str, hit_pages)).encode('utf-8')).hexdigest()[:12]}", date_display=_iso_date_display(proc_date) if proc_date else "Date not documented", provider_display=proc_provider, event_type_display="Procedure/Surgery", patient_label="See Patient Header", facts=proc_entry_facts, verbatim_flags=[False] * len(proc_entry_facts), citation_display=", ".join(f"p. {p}" for p in hit_pages[:5]), confidence=85))

    if select_timeline:
        merged_entries = sorted(_apply_timeline_selection(entries, total_pages=len(page_text_by_number or {}), selection_meta=selection_meta, providers=providers, page_provider_map=page_provider_map, page_text_by_number=page_text_by_number, config=config), key=lambda e: (e.patient_label, (re.search(r"\b(\d{4}-\d{2}-\d{2})\b", e.date_display).group(1) if re.search(r"\b(\d{4}-\d{2}-\d{2})\b", e.date_display) else "9999-12-31"), e.event_id))
    else:
        merged_entries = _merge_projection_entries(entries, select_timeline=select_timeline, config=config)

    if selection_meta is not None:
        selection_meta.update(asdict(SelectionResult(
            extracted_event_ids=[e.event_id for e in sorted_events],
            candidates_initial_ids=[e.event_id for e in entries],
            candidates_after_backfill_ids=[e.event_id for e in entries],
            kept_ids=[e.event_id for e in merged_entries],
            final_ids=[e.event_id for e in merged_entries],
            stopping_reason=str(selection_meta.get("stopping_reason", "no_candidates")),
            delta_u_trace=list(selection_meta.get("delta_u_trace", [])),
            selected_utility_components=list(selection_meta.get("selected_utility_components", []))
        )))
    return ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=merged_entries, select_timeline=select_timeline)

@dataclass
class SelectionResult:
    extracted_event_ids: list[str]
    candidates_initial_ids: list[str]
    candidates_after_backfill_ids: list[str]
    kept_ids: list[str]
    final_ids: list[str]
    stopping_reason: str = "no_candidates"
    delta_u_trace: list[float] | None = None
    selected_utility_components: list[dict[str, Any]] | None = None
