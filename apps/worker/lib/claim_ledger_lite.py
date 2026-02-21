from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict

from packages.shared.utils.claim_utils import (
    parse_iso,
    stable_id,
    extract_body_region,
)
from apps.worker.lib.noise_filter import is_noise_span
from apps.worker.steps.events.report_quality import sanitize_for_report
from packages.shared.models import ClaimEdge, ClaimType, Event

_CLAIM_TYPES = {c.value for c in ClaimType}

_MEDICAL_TOKENS = {
    "pain", "rom", "strength", "diagnosis", "assessment", "impression", "mri", "ct", "xray", "x-ray",
    "radiculopathy", "stenosis", "herniation", "fracture", "sprain", "strain", "procedure", "injection",
    "therapy", "pt", "ot", "chiro", "discharge", "admission", "numbness", "tingling", "spasm", "sciatica",
}
_DX_RELEVANT_RE = re.compile(
    r"\b("
    r"neck pain|cervical|low back pain|lumbar|thoracic|back pain|"
    r"strain|sprain|radiculopathy|sciatica|disc|herniation|protrusion|stenosis|"
    r"fracture|dislocation|myofascial|spasm|whiplash|cervicalgia|lumbago|paresthesia"
    r")\b",
    re.IGNORECASE,
)
_DX_EXCLUDE_RE = re.compile(
    r"\b(years ago|appendectomy|arthroscopy|no history of|reports no regular use of tobacco)\b",
    re.IGNORECASE,
)
_LOW_VALUE_RE = re.compile(
    r"(i,\s*the undersigned|consent to the performance|risks?,\s*benefits?,\s*and alternatives?|"
    r"discharge summary\s+discharge summary|from:\s*\(\d{3}\)\s*\d{3}[-\d]+\s*to:\s*records dept|"
    r"\(\d{3}\)\s*\d{3}[-\d]+|fax:|monitoring:\s*patient remained hemodynamically stable|"
    r"procedural timeout was performed immediately prior)",
    re.IGNORECASE,
)
_ICD_RE = re.compile(r"\b[A-TV-Z][0-9]{2}(?:\.[0-9A-TV-Z]{1,4})?\b")
_PT_DX_RE = re.compile(
    r"\b(cervicalgia|lumbago|cervical strain|lumbar strain|thoracic strain|"
    r"radiculopathy|sciatica|myofascial pain|whiplash|sprain|strain|muscle spasm)\b",
    re.IGNORECASE,
)

_MATERIALITY_WEIGHT = {
    "PROCEDURE": 3,
    "IMAGING_FINDING": 3,
    "INJURY_DX": 2,
    "MEDICATION_CHANGE": 2,
    "WORK_RESTRICTION": 2,
    "TREATMENT_VISIT": 1,
    "SYMPTOM": 1,
    "GAP_IN_CARE": 2,
    "PRE_EXISTING_MENTION": 1,
}

_MEDICATION_FILTER_RE = re.compile(
    r"\b(opioid|oxycodone|hydrocodone|morphine|tramadol|fentanyl|codeine|gabapentin|pregabalin|cyclobenzaprine|"
    r"methocarbamol|tizanidine|meloxicam|naproxen|ibuprofen|diclofenac|celecoxib|prednisone|medrol|methylprednisolone|"
    r"muscle relaxant|nsaid|steroid|analgesic|started|stopped|discontinued|switched|increased|decreased)\b",
    re.IGNORECASE,
)

_logger = logging.getLogger(__name__)

TOP_SELECTION_CONFIG = {
    "required_buckets": ["procedure", "imaging", "specialist", "doi_start", "pt_key", "gap", "med_or_work"],
    "treatment_visit_cap": 4,
    "symptom_cap": 3,
    "preexisting_cap": 1,
}

# Deprecated: kept for one release while external call-sites migrate to ClaimEdge.
ClaimRow = ClaimEdge

_stable_id = stable_id
_extract_body_region = extract_body_region


def _extract_tokens(text: str, max_tokens: int = 6) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    toks = [t for t in toks if len(t) > 2][:max_tokens]
    return toks or ["none"]


def _parse_date(entry_date_display: str) -> str:
    parsed = parse_iso(entry_date_display)
    return parsed.isoformat() if parsed else "unknown"


def _claim_type_for_fact(event_type_display: str, fact: str) -> str:
    low = fact.lower()
    et = (event_type_display or "").lower()
    if re.search(r"\b(work restriction|unable to work|off work|no work)\b", low):
        return "WORK_RESTRICTION"
    if re.search(r"\b(started|stopped|discontinued|switched|increased|decreased|medication)\b", low):
        return "MEDICATION_CHANGE"
    if "procedure" in et or "surgery" in et or re.search(r"\b(injection|epidural|procedure|surgery)\b", low):
        return "PROCEDURE"
    if "imaging" in et or re.search(r"\b(mri|ct|x-?ray|impression|radiology|finding)\b", low):
        return "IMAGING_FINDING"
    if _ICD_RE.search(fact) or _PT_DX_RE.search(low):
        return "INJURY_DX"
    if re.search(r"\b(diagnosis|dx|assessment|impression|problem list|a/p|treatment diagnosis|medical diagnosis|primary dx|secondary dx)\b", low):
        return "INJURY_DX"
    if re.search(r"\b(diagnosis|assessment|impression|radiculopathy|strain|sprain|herniation|stenosis)\b", low):
        return "INJURY_DX"
    if re.search(r"\b(pre-existing|chronic|degenerative|prior)\b", low):
        return "PRE_EXISTING_MENTION"
    if re.search(r"\b(pain|numbness|tingling|spasm|weakness|decreased rom)\b", low):
        return "SYMPTOM"
    return "TREATMENT_VISIT"


def _support_score(claim_type: str, assertion: str, flags: set[str]) -> int:
    low = assertion.lower()
    score = 0
    if claim_type == "IMAGING_FINDING" and re.search(r"\b(impression|finding|abnormal|fracture|tear|herniation|stenosis)\b", low):
        score += 3
    if claim_type == "INJURY_DX":
        score += 2
    if claim_type == "PROCEDURE":
        score += 2
    if claim_type == "SYMPTOM":
        score += 1
    if "laterality_conflict" in flags or "timing_inconsistency" in flags:
        score -= 3
    if "degenerative_language" in flags:
        score -= 2
    if "treatment_gap" in flags:
        score -= 2
    return max(0, min(10, score))


def _strength(score: int) -> str:
    if score >= 6:
        return "Strong"
    if score >= 3:
        return "Medium"
    return "Weak"


def _is_admin_only(text: str) -> bool:
    return bool(re.search(r"\b(request|fax|schedule|billing|authorization)\b", text.lower()))


def _is_nonsense(text: str) -> bool:
    if not text or is_noise_span(text):
        return True
    tokens = re.findall(r"[a-z]+", text.lower())
    if not tokens:
        return True
    single_letter = sum(1 for t in tokens if len(t) == 1)
    med_hits = sum(1 for t in tokens if t in _MEDICAL_TOKENS)
    non_med_ratio = 1.0 - (med_hits / max(1, len(tokens)))
    if single_letter / max(1, len(tokens)) > 0.25:
        return True
    if len(tokens) >= 16 and non_med_ratio > 0.85:
        return True
    return False


def _is_relevant_dx(assertion: str) -> bool:
    low = (assertion or "").strip().lower()
    if not low:
        return False
    if _DX_EXCLUDE_RE.search(low):
        return False
    if re.search(r"\b[A-TV-Z][0-9]{2}(?:\.[0-9A-TV-Z]{1,4})?\b", assertion or ""):
        return True
    return bool(_DX_RELEVANT_RE.search(low))


def _clean_assertion(text: str) -> str:
    out = sanitize_for_report(text or "").strip()
    if not out:
        return ""
    out = re.sub(r"\bDISCHARGE SUMMARY\s+Discharge Summary\b", "Discharge summary", out, flags=re.IGNORECASE)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out


def build_claim_edges(
    entries: list,
    *,
    material_gap_rows: list[dict] | None = None,
    raw_events: list[Event] | None = None,
) -> list[ClaimEdge]:
    rows: list[ClaimEdge] = []
    by_date_region_side: dict[tuple[str, str], set[str]] = defaultdict(set)

    for entry in entries:
        date_str = _parse_date(getattr(entry, "date_display", ""))
        provider = sanitize_for_report(getattr(entry, "provider_display", "") or "Unknown")
        patient_label = getattr(entry, "patient_label", "Unknown Patient")
        citations = [c.strip() for c in re.split(r"\s*\|\s*", str(getattr(entry, "citation_display", "") or "")) if c.strip()]
        facts = [sanitize_for_report(f) for f in list(getattr(entry, "facts", []) or []) if sanitize_for_report(f)]
        if not facts:
            continue
        event_type_display = str(getattr(entry, "event_type_display", "") or "")
        for fact in facts:
            claim_type = _claim_type_for_fact(event_type_display, fact)
            if claim_type not in _CLAIM_TYPES:
                continue
            flags: set[str] = set()
            low = fact.lower()
            if date_str == "unknown":
                flags.add("timing_ambiguous")
            if re.search(r"\b(degenerative|chronic|age-related|spondylosis)\b", low) and not re.search(r"\b(acute|post[- ]?traumatic|post[- ]?mva|after mva)\b", low):
                flags.add("degenerative_language")
            side = "left" if "left" in low else ("right" if "right" in low else "")
            region = _extract_body_region(low)
            if side:
                by_date_region_side[(date_str, region)].add(side)

            assertion = _clean_assertion(fact)[:220].strip()
            if not assertion:
                continue

            base = _support_score(claim_type, assertion, flags)
            materiality_weight = _MATERIALITY_WEIGHT.get(claim_type, 1)
            row_id = _stable_id(
                [
                    claim_type,
                    date_str,
                    region,
                    provider.lower(),
                    *(_extract_tokens(assertion)),
                ]
            )
            rows.append(
                ClaimRow(
                    id=row_id,
                    event_id=getattr(entry, "event_id", ""),
                    patient_label=patient_label,
                    claim_type=claim_type,
                    date=date_str,
                    body_region=region,
                    provider=provider,
                    assertion=assertion,
                    citations=citations[:3],
                    support_score=base,
                    support_strength=_strength(base),
                    flags=sorted(flags),
                    materiality_weight=materiality_weight,
                    selection_score=base * materiality_weight,
                )
            )

    for row in rows:
        sides = by_date_region_side.get((row.date, row.body_region), set())
        if "left" in sides and "right" in sides:
            row.flags = sorted(set(row.flags) | {"laterality_conflict"})
            row.support_score = max(0, row.support_score - 3)
            row.support_strength = _strength(row.support_score)
            row.selection_score = row.support_score * row.materiality_weight

    if material_gap_rows:
        for gap_row in material_gap_rows:
            gap = gap_row.get("gap")
            if not gap:
                continue
            duration = int(getattr(gap, "duration_days", 0) or 0)
            if duration < 45:
                continue
            date_str = str(getattr(gap, "start_date", "") or "unknown")
            patient_label = str(gap_row.get("patient_label") or "Unknown Patient")
            citations = []
            for key in ("last_before", "first_after"):
                c = str((gap_row.get(key) or {}).get("citation_display") or "").strip()
                if c:
                    citations.append(c)
            assertion = f"Treatment gap of {duration} days identified."
            score = 3 if duration < 90 else 5
            row_id = _stable_id(["GAP_IN_CARE", date_str, patient_label, str(duration)])
            rows.append(
                ClaimRow(
                    id=row_id,
                    event_id=f"gap:{getattr(gap, 'gap_id', row_id)}",
                    patient_label=patient_label,
                    claim_type="GAP_IN_CARE",
                    date=date_str,
                    body_region="general",
                    provider="Unknown",
                    assertion=assertion,
                    citations=citations[:2],
                    support_score=score,
                    support_strength=_strength(score),
                    flags=["treatment_gap"],
                    materiality_weight=_MATERIALITY_WEIGHT["GAP_IN_CARE"],
                    selection_score=score * _MATERIALITY_WEIGHT["GAP_IN_CARE"],
                )
            )

    if raw_events:
        for evt in raw_events:
            date_str = "unknown"
            if evt.date and evt.date.value:
                try:
                    date_str = evt.date.sort_date().isoformat()
                except Exception:
                    date_str = "unknown"
            patient_label = "See Patient Header"
            provider = str(evt.provider_id or "Unknown")
            page_nums = sorted(set(evt.source_page_numbers or []))
            citations = [f"p. {p}" for p in page_nums[:3]] or (["record refs"] if evt.citation_ids else [])

            def _emit(assertion: str, claim_type: str, extra_flags: set[str] | None = None):
                assertion = _clean_assertion(assertion)
                if not assertion:
                    return
                low = assertion.lower()
                flags = set(extra_flags or set())
                if claim_type == "PRE_EXISTING_MENTION":
                    flags.add("pre_existing_overlap")
                if re.search(r"\b(degenerative|chronic|age-related|spondylosis)\b", low) and not re.search(r"\b(acute|post[- ]?traumatic|post[- ]?mva)\b", low):
                    flags.add("degenerative_language")
                region = _extract_body_region(low)
                score = _support_score(claim_type, assertion, flags)
                materiality_weight = _MATERIALITY_WEIGHT.get(claim_type, 1)
                row_id = _stable_id(
                    [claim_type, date_str, region, provider.lower(), *_extract_tokens(assertion)]
                )
                rows.append(
                    ClaimRow(
                        id=row_id,
                        event_id=evt.event_id,
                        patient_label=patient_label,
                        claim_type=claim_type,
                        date=date_str,
                        body_region=region,
                        provider=provider,
                        assertion=assertion[:220],
                        citations=citations,
                        support_score=score,
                        support_strength=_strength(score),
                        flags=sorted(flags),
                        materiality_weight=materiality_weight,
                        selection_score=score * materiality_weight,
                    )
                )

            for fact in evt.diagnoses:
                _emit(fact.text, "INJURY_DX")
            for fact in evt.procedures:
                _emit(fact.text, "PROCEDURE")
            for fact in evt.medications:
                ctype = "MEDICATION_CHANGE" if re.search(r"\b(start|stop|switch|increase|decrease|discontinue)\b", fact.text, re.IGNORECASE) else "TREATMENT_VISIT"
                _emit(fact.text, ctype)
            for fact in evt.facts:
                ctype = _claim_type_for_fact(evt.event_type.value.replace("_", " "), fact.text)
                _emit(fact.text, ctype)
            if evt.imaging and evt.imaging.impression:
                for fact in evt.imaging.impression:
                    _emit(fact.text, "IMAGING_FINDING")

    dedup: dict[str, ClaimEdge] = {}
    for row in rows:
        prev = dedup.get(row.id)
        if prev is None:
            dedup[row.id] = row
            continue
        if row.selection_score > prev.selection_score:
            dedup[row.id] = row
        elif row.selection_score == prev.selection_score and len(row.citations) > len(prev.citations):
            dedup[row.id] = row

    final_rows = list(dedup.values())
    final_rows.sort(key=lambda r: (r.date, -r.selection_score, r.claim_type, r.id))
    cited_count = sum(1 for r in final_rows if r.citations)
    _logger.info(
        "build_claim_edges: %d edges from %d entries + %d raw_events (%d with citations)",
        len(final_rows),
        len(entries),
        len(raw_events or []),
        cited_count,
    )
    return final_rows


def build_claim_ledger_lite(
    entries: list,
    *,
    material_gap_rows: list[dict] | None = None,
    raw_events: list[Event] | None = None,
) -> list[dict]:
    edges = build_claim_edges(entries, material_gap_rows=material_gap_rows, raw_events=raw_events)
    return [edge.model_dump(mode="json") for edge in edges]


def depo_safe_rewrite(sentence: str, claim_rows: list[dict]) -> str:
    safe = sanitize_for_report(sentence or "").strip()
    if not safe:
        return safe
    low = safe.lower()
    flags = {f for row in claim_rows for f in (row.get("flags") or [])}
    types = {str(row.get("claim_type") or "") for row in claim_rows}
    assertions = " ".join(str(row.get("assertion") or "") for row in claim_rows).lower()

    has_explicit_causation = bool(re.search(r"\b(caused by|due to|result of|related to)\b", assertions))
    if re.search(r"\b(caused by|due to|result of)\b", low) and not has_explicit_causation:
        safe = re.sub(r"\b(caused by|due to|result of)\b", "reported after", safe, flags=re.IGNORECASE)

    if re.search(r"\b(permanent|permanency)\b", low):
        has_permanent_support = bool(re.search(r"\b(permanent|permanency)\b", assertions))
        if not has_permanent_support:
            safe = re.sub(r"\b(permanent|permanency)\b", "ongoing", safe, flags=re.IGNORECASE)

    if re.search(r"\b(unable to work|cannot work|off work)\b", low) and "WORK_RESTRICTION" not in types:
        safe = re.sub(
            r"\b(unable to work|cannot work|off work)\b",
            "work status impact documented",
            safe,
            flags=re.IGNORECASE,
        )

    if "laterality_conflict" in flags and re.search(r"\b(left|right)\b", safe.lower()):
        safe = re.sub(r"\b(left|right)\b", "reported", safe, flags=re.IGNORECASE)

    return re.sub(r"\s{2,}", " ", safe).strip()


def select_top_claim_rows(claim_rows: list[dict], limit: int = 10) -> list[dict]:
    claim_label_map = {
        "INJURY_DX": "Diagnosis",
        "SYMPTOM": "Symptom",
        "IMAGING_FINDING": "Imaging Finding",
        "PROCEDURE": "Procedure/Surgery",
        "MEDICATION_CHANGE": "Medication Change",
        "WORK_RESTRICTION": "Work Restriction",
        "TREATMENT_VISIT": "Treatment Visit",
        "GAP_IN_CARE": "Treatment Gap",
        "PRE_EXISTING_MENTION": "Pre-existing Mention",
    }

    def _render_key(row: dict) -> tuple[str, str, str]:
        date_key = str(row.get("date") or "").strip().lower()
        label_key = claim_label_map.get(str(row.get("claim_type") or ""), "Clinical Event").strip().lower()
        cite_key = re.sub(r"\s+", " ", str(row.get("citation") or "").strip().lower())
        return (date_key, label_key, cite_key)

    def _bucket_for_row(r: dict) -> str:
        ctype = str(r.get("claim_type") or "")
        text = str(r.get("assertion") or "").lower()
        if re.search(r"\b(chief complaint|rear[- ]end|mva|mvc|presents via|emergency)\b", text):
            return "doi_start"
        if ctype == "IMAGING_FINDING":
            return "imaging"
        if ctype == "PROCEDURE":
            return "procedure"
        if re.search(r"\b(orthopedic|specialist|consult|referral)\b", text):
            return "specialist"
        if ctype == "GAP_IN_CARE":
            return "gap"
        if ctype in {"MEDICATION_CHANGE", "WORK_RESTRICTION"}:
            return "med_or_work"
        if ctype == "INJURY_DX":
            return "diagnosis"
        if re.search(r"\b(initial evaluation|eval|start of care|discharge)\b", text):
            return "pt_key"
        if ctype == "SYMPTOM":
            return "symptom"
        if ctype == "TREATMENT_VISIT":
            return "visit"
        return "other"

    def _is_low_signal_procedure(text: str) -> bool:
        low = text.lower()
        if re.search(r"\b(bp|hr|sat|spo2|monitoring|hemodynamically stable)\b", low) and not re.search(
            r"\b(epidural|injection|interlaminar|transforaminal|fluoroscopy|depo-?medrol|lidocaine|discectomy|fusion|laminectomy)\b",
            low,
        ):
            return True
        return False

    candidates: list[dict] = []
    seen_semantic: set[tuple[str, str]] = set()
    for row in claim_rows:
        assertion = str(row.get("assertion") or "")
        if not assertion:
            continue
        if _is_nonsense(assertion):
            continue
        if _is_admin_only(assertion):
            continue
        if _LOW_VALUE_RE.search(assertion):
            continue
        ctype = str(row.get("claim_type") or "")
        if ctype not in _CLAIM_TYPES:
            continue
        if ctype == "PROCEDURE" and _is_low_signal_procedure(assertion):
            continue
        if ctype == "INJURY_DX" and not _is_relevant_dx(assertion):
            continue
        if ctype == "PRE_EXISTING_MENTION":
            if not re.search(r"\b(pre-existing|prior|degenerative|chronic|history)\b", assertion.lower()):
                continue
            if int(row.get("support_score") or 0) < 2:
                continue
        if ctype == "MEDICATION_CHANGE":
            if not _MEDICATION_FILTER_RE.search(assertion.lower()):
                continue
        if ctype in {"TREATMENT_VISIT", "SYMPTOM"} and not re.search(
            r"\b(diagnosis|impression|assessment|mri|ct|x-?ray|procedure|injection|radiculopathy|herniation|strain|sprain|pain|rom|strength|hospital|admission|discharge|emergency|ed)\b",
            assertion.lower(),
        ):
            continue
        cites = [c for c in (row.get("citations") or []) if str(c).strip()]
        if not cites:
            continue
        semantic_assertion = re.sub(r"[^a-z0-9]+", " ", assertion.lower()).strip()
        semantic_assertion = re.sub(r"\b(discharge summary|initial evaluation|medical history|history of present illness)\b", "", semantic_assertion).strip()
        semantic_key = ("any_date", semantic_assertion[:140])
        if semantic_key in seen_semantic:
            continue
        seen_semantic.add(semantic_key)
        row = dict(row)
        row["citation"] = " | ".join(cites[:2])
        row["score"] = int(row.get("selection_score") or 0)
        row["bucket"] = _bucket_for_row(row)
        candidates.append(row)

    candidates.sort(
        key=lambda r: (
            -int(r.get("score") or 0),
            str(r.get("date") or ""),
            str(r.get("id") or ""),
        )
    )

    selected: list[dict] = []
    selected_ids: set[str] = set()
    selected_type_date: set[tuple[str, str]] = set()
    selected_render_keys: set[tuple[str, str, str]] = set()
    by_type: Counter[str] = Counter()
    required_buckets = list(TOP_SELECTION_CONFIG["required_buckets"])
    by_bucket: defaultdict[str, list[dict]] = defaultdict(list)
    for row in candidates:
        by_bucket[str(row.get("bucket") or "other")].append(row)
    for b in required_buckets:
        if len(selected) >= limit:
            break
        rows = by_bucket.get(b) or []
        if not rows:
            continue
        pick = rows[0]
        rid = str(pick.get("id") or "")
        if rid and rid in selected_ids:
            continue
        ctype = str(pick.get("claim_type") or "")
        dkey = str(pick.get("date") or "")
        td_key = (ctype, dkey)
        if td_key in selected_type_date:
            continue
        rkey = _render_key(pick)
        if rkey in selected_render_keys:
            continue
        selected.append(pick)
        if rid:
            selected_ids.add(rid)
        selected_type_date.add(td_key)
        selected_render_keys.add(rkey)
        by_type[ctype] += 1

    for row in candidates:
        rid = str(row.get("id") or "")
        if rid and rid in selected_ids:
            continue
        ctype = str(row.get("claim_type") or "")
        dkey = str(row.get("date") or "")
        td_key = (ctype, dkey)
        if td_key in selected_type_date and ctype in {"IMAGING_FINDING", "SYMPTOM", "TREATMENT_VISIT", "INJURY_DX"}:
            continue
        rkey = _render_key(row)
        if rkey in selected_render_keys:
            continue
        if ctype == "TREATMENT_VISIT" and by_type[ctype] >= int(TOP_SELECTION_CONFIG["treatment_visit_cap"]):
            continue
        if ctype == "SYMPTOM" and by_type[ctype] >= int(TOP_SELECTION_CONFIG["symptom_cap"]):
            continue
        if ctype == "PRE_EXISTING_MENTION" and by_type[ctype] >= int(TOP_SELECTION_CONFIG["preexisting_cap"]):
            continue
        selected.append(row)
        if rid:
            selected_ids.add(rid)
        selected_type_date.add(td_key)
        selected_render_keys.add(rkey)
        by_type[ctype] += 1
        if len(selected) >= limit:
            break

    # ensure at least one high-impact item if available
    if selected:
        has_high = any(str(r.get("claim_type")) in {"INJURY_DX", "IMAGING_FINDING", "PROCEDURE"} for r in selected)
        if not has_high:
            for row in candidates:
                if str(row.get("claim_type")) in {"INJURY_DX", "IMAGING_FINDING", "PROCEDURE"}:
                    selected[-1] = row
                    break

    return selected


def summarize_risk_flags(claim_rows: list[dict]) -> list[str]:
    allowed = {
        "laterality_conflict",
        "pre_existing_overlap",
        "treatment_gap",
        "degenerative_language",
        "timing_inconsistency",
        "timing_ambiguous",
    }
    counts: Counter[str] = Counter()
    for row in claim_rows:
        for flag in (row.get("flags") or []):
            if flag in allowed:
                counts[flag] += 1
    out: list[str] = []
    for flag in sorted(counts.keys()):
        out.append(f"{flag.replace('_', ' ').title()} ({counts[flag]} mention(s))")
    return out
