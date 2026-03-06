"""
Build a pipeline-side RendererManifest for the chronology PDF renderer.

This step performs source selection / structuring only using already-computed pipeline outputs.
It does not run new extraction.
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from datetime import datetime
from datetime import date
from typing import Any

from packages.shared.models import Citation, Event, RendererManifest, RendererDoiField, RendererCitationValue, RendererPtSummary, PromotedFinding, BucketEvidence, RendererCaseSkeleton, RendererCaseSkeletonItem
from packages.shared.utils.scoring_utils import is_ed_event
from packages.shared.utils.noise_utils import is_fax_header_noise


_SENTINEL_DATES = {"1900-01-01", "0001-01-01", "unknown", "undated", ""}

_CATEGORY_ORDER = {
    "objective_deficit": 0,
    "imaging": 1,
    "diagnosis": 2,
    "procedure": 3,
    "treatment": 4,
    "visit_count": 5,
    "symptom": 6,
}

_GENERIC_PLACEHOLDER_PATTERNS = [
    re.compile(r"\b(?:impression|assessment|consultation)\s+(?:documented|reviewed|noted)\b", re.I),
    re.compile(r"\bfollow-?up and treatment planning noted\b", re.I),
    re.compile(r"\bfax id\b", re.I),
    re.compile(r"\bpage\s+\d+\b", re.I),
]

_NEGATIVE_IMAGING_PATTERNS = [
    re.compile(r"\bno acute\b", re.I),
    re.compile(r"\bunremarkable\b", re.I),
    re.compile(r"\bno fracture\b", re.I),
    re.compile(r"\bno dislocation\b", re.I),
    re.compile(r"\bnormal disc signal\b", re.I),
    re.compile(r"\bno canal stenosis\b", re.I),
    re.compile(r"\bno significant degenerative\b", re.I),
    re.compile(r"\bdisc spaces?:\s*preserved\b", re.I),
    re.compile(r"\bpreserved\b", re.I),
]
_SNAP_NUMERIC_PAT = re.compile(r"\b\d{1,3}(?:/\d{1,3})?\b")
_SNAP_PAIN_PAT = re.compile(r"\b(pain(?:\s*(?:score|level|severity))?\s*[:=]?\s*\d{1,2}\s*/\s*10)\b", re.I)
_SNAP_VITALS_PAT = re.compile(r"\b(?:bp|blood pressure|hr|heart rate|rr|respiratory rate|spo2)\b", re.I)
_SNAP_ROM_PAT = re.compile(r"\b(?:rom|range of motion|strength|weakness|diminished reflex|spasm)\b", re.I)
_SNAP_MEDS_PAT = re.compile(r"\b(?:mg|mcg|ml|toradol|ketorolac|ibuprofen|acetaminophen|lidocaine|depo-?medrol|flexeril|gabapentin|naproxen)\b", re.I)
_SNAP_DISPO_PAT = re.compile(r"\b(?:discharge|home care|return precautions|follow-?up|final pain)\b", re.I)

_OBJECTIVE_DEFICIT_PAT = re.compile(r"\b(weakness|strength|reflex|diminished|range of motion|rom|spasm|lordosis|[0-5]/5)\b", re.I)
_STRUCTURAL_IMAGING_PAT = re.compile(r"\b(disc|foramen|foraminal|radicul|stenosis|herniat|protrusion|compression|displacement|tear|fracture)\b", re.I)
_TRAILING_FRAGMENT_PATTERNS = [
    re.compile(r"\bThis directly\b.*$", re.I),
    re.compile(r"\bThis indicates\b.*$", re.I),
    re.compile(r"\bThis demonstrates\b.*$", re.I),
]

_CLAIM_GATE_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "into", "from", "page",
    "patient", "record", "records", "documented", "noted", "impression",
    "assessment", "diagnosis", "finding", "findings",
}

_META_LANGUAGE_RE = re.compile(
    r"\b("
    r"identified from source|documented in cited records|markers|extracted|encounter identified|"
    r"not stated in records|packet|summaries vary|observed range|intensity reference|"
    r"reconciliation|displays? the|reference only|not available|unknown provider|date not documented|"
    r"chronology eval|litigation safety check|verified in extracted chronology|not yet litigation-safe|"
    r"attorney-facing chronology|recommended attorney action|defense vulnerabilities|case readiness|"
    r"defense may exploit|review recommended|qa_[a-z0-9_]+|ar_[a-z0-9_]+"
    r")\b",
    re.IGNORECASE,
)

_GENERIC_SYNTHETIC_DIAGNOSIS_RE = re.compile(
    r"\b(?:medical condition|primary diagnosis:\s*medical condition|secondary diagnosis:\s*medical condition)\s+[a-z0-9.]+\b",
    re.IGNORECASE,
)
_ADMIN_RECORD_RE = re.compile(
    r"\b(?:admission|discharge|encounter|visit)\s+record\s*:\s*#?\d+\b",
    re.IGNORECASE,
)
_TIMING_ONLY_TREATMENT_RE = re.compile(
    r"^\s*admitted\s*:\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?\s*\|\s*discharged\s*:\s*\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?\s*$",
    re.IGNORECASE,
)
_LOW_VALUE_TREATMENT_RE = re.compile(
    r"\b(?:admission record|discharge summary|discharged home(?: with instructions)?|discharged in stable condition|admitted for observation|presented with worsening medical condition|patient remained hemodynamically stable)\b",
    re.IGNORECASE,
)
_SUBSTANTIVE_DIAGNOSIS_RE = re.compile(
    r"\b("
    r"fracture|dislocation|disc|herniat|protrusion|stenosis|radicul|sprain|strain|tear|"
    r"weakness|deficit|neuropathy|concussion|tbi|meniscus|labral|rotator|foramen|foraminal|compression"
    r")\b",
    re.IGNORECASE,
)
_SUBSTANTIVE_TREATMENT_RE = re.compile(
    r"\b("
    r"injection|epidural|procedure|surgery|fusion|arthroscop|repair|open reduction|orif|"
    r"physical therapy|therapy|work restriction|medication|follow-?up|consult"
    r")\b",
    re.IGNORECASE,
)
_LAB_PANEL_RE = re.compile(
    r"\b(?:sodium|potassium|chloride|creatinine|glucose|bun|wbc|hgb|hemoglobin|platelets?)\s*:\s*[-+]?\d",
    re.IGNORECASE,
)
_IDENTIFIER_ONLY_RE = re.compile(r"^\s*(?:patient id|account|record number)\s*:?\s*#?\d+\s*$|^\s*#?\d+\s*$", re.IGNORECASE)
_HEADER_ONLY_RE = re.compile(r"^\s*(?:discharge summary|admission record|diagnosis|assessment|plan of care)\s*$", re.IGNORECASE)


def clean_meta_language(text: str | None) -> str:
    if not text:
        return ""
    low = text.strip().lower()
    if low in {"not available", "unknown provider", "date not documented", "unknown", "undated"}:
        return ""
    if _META_LANGUAGE_RE.search(text):
        if len(text) < 150:
            return ""
        return _META_LANGUAGE_RE.sub("", text).strip()
    return text.strip()


def _is_low_value_claim_for_promotion(
    assertion: str,
    *,
    category: str,
    claim_type: str,
    support_score: float | int | None,
    selection_score: float | int | None,
) -> bool:
    text = (assertion or "").strip()
    low = text.lower()
    if not text:
        return True
    if _GENERIC_SYNTHETIC_DIAGNOSIS_RE.search(text):
        return True
    if _ADMIN_RECORD_RE.search(text):
        return True
    if _TIMING_ONLY_TREATMENT_RE.match(text):
        return True
    if _LAB_PANEL_RE.search(text):
        return True
    if _IDENTIFIER_ONLY_RE.match(text):
        return True
    if _HEADER_ONLY_RE.match(text):
        return True
    if _LOW_VALUE_TREATMENT_RE.search(text) and not _SUBSTANTIVE_TREATMENT_RE.search(text):
        return True
    if category == "treatment":
        pass
    if category == "diagnosis":
        if ("medical condition" in low or "condition " in low) and not _SUBSTANTIVE_DIAGNOSIS_RE.search(text):
            return True
        if not _SUBSTANTIVE_DIAGNOSIS_RE.search(text):
            sel = float(selection_score or 0)
            sup = float(support_score or 0)
            if sel < 20 and sup < 3:
                return True
    if category == "treatment" and not _SUBSTANTIVE_TREATMENT_RE.search(text):
        sel = float(selection_score or 0)
        sup = float(support_score or 0)
        if sel < 20 and sup < 3:
            return True
    if category in {"symptom", "visit_count"}:
        return False
    if claim_type == "TREATMENT_VISIT" and category == "diagnosis" and not _SUBSTANTIVE_DIAGNOSIS_RE.search(text):
        return True
    return False


def _iso_from_event(event: Event) -> tuple[str | None, str | None]:
    d = getattr(event, "date", None)
    if not d or not getattr(d, "value", None):
        return (None, None)
    v = d.value
    if isinstance(v, date):
        s = v.isoformat()
        if s in _SENTINEL_DATES:
            return (None, None)
        return (s, s)
    start = getattr(v, "start", None)
    end = getattr(v, "end", None)
    s = start.isoformat() if isinstance(start, date) else None
    e = end.isoformat() if isinstance(end, date) else None
    if s in _SENTINEL_DATES:
        s = None
    if e in _SENTINEL_DATES:
        e = None
    return (s, e or s)


def _collect_fact_text(event: Event) -> str:
    parts: list[str] = []
    for pool_name in ("facts", "diagnoses", "exam_findings", "procedures", "treatment_plan"):
        for fact in getattr(event, pool_name, []) or []:
            txt = str(getattr(fact, "text", "") or "").strip()
            if txt:
                parts.append(txt)
    return " ".join(parts)


def _event_text_blobs(event: Event) -> list[str]:
    blobs: list[str] = []
    for val in (getattr(event, "reason_for_visit", None), getattr(event, "chief_complaint", None)):
        txt = str(val or "").strip()
        if txt:
            blobs.append(txt)
    for pool_name in ("facts", "diagnoses", "exam_findings", "procedures", "treatment_plan"):
        for fact in getattr(event, pool_name, []) or []:
            txt = str(getattr(fact, "text", "") or "").strip()
            if txt and not getattr(fact, "technical_noise", False):
                blobs.append(txt)
    imaging = getattr(event, "imaging", None)
    for fact in getattr(imaging, "impression", []) or []:
        txt = str(getattr(fact, "text", "") or "").strip()
        if txt and not getattr(fact, "technical_noise", False):
            blobs.append(txt)
    return blobs


def _build_doi(events: list[Event]) -> RendererDoiField:
    dated: list[tuple[str, Event]] = []
    for e in events:
        start, _end = _iso_from_event(e)
        if start and start not in _SENTINEL_DATES:
            dated.append((start, e))
    if not dated:
        return RendererDoiField(value=None, citation_ids=[], source="not_found")
    dated.sort(key=lambda x: x[0])
    doi, evt = dated[0]
    return RendererDoiField(value=doi, citation_ids=list(getattr(evt, "citation_ids", []) or []), source="inferred")


def _best_objective_clause(text: str) -> str:
    parts = [p.strip(" -•\t") for p in re.split(r"[.;]\s+", text or "") if p.strip()]
    for p in parts:
        if _OBJECTIVE_DEFICIT_PAT.search(p) and not re.search(r"\bno acute fracture\b", p, re.I):
            p = re.sub(r"\bThere is no evidence\b.*$", "", p, flags=re.I).strip()
            return p
    out = re.sub(r"\bThere is no evidence\b.*$", "", text or "", flags=re.I).strip()
    return out


def _clean_citation_snippet_for_finding(text: str) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    s = re.sub(r"^[\s\-•*\d\.\)]+", "", s)
    # Prefer a complete sentence/statement to avoid truncated tails like "This directly"
    if len(s) > 140:
        # Keep up to the last punctuation before the limit if available.
        cutoff = max(s.rfind(".", 0, 170), s.rfind(";", 0, 170))
        if cutoff >= 40:
            s = s[: cutoff + 1]
    # Remove obvious truncated tail fragments.
    s = re.sub(r"\bThere is no evidence\b.*$", "", s, flags=re.I).strip()
    for pat in _TRAILING_FRAGMENT_PATTERNS:
        s = pat.sub("", s).strip()
    s = re.sub(r"[,:;\\-]\s*$", "", s).strip()
    return s


def _clean_finding_label(text: str) -> str:
    s = _clean_citation_snippet_for_finding(text or "")
    s = re.sub(r"^\s*The MRI shows\s+", "", s, flags=re.I).strip()
    s = re.sub(r"^\s*ASSESSMENT\s+AND\s+TREATMENT\s+PLAN\s*", "", s, flags=re.I).strip()
    s = re.sub(r"^\s*(assessment|impression|diagnosis(?:es)?|treatment plan)\s*[:\-]\s*", "", s, flags=re.I).strip()
    s = re.sub(r"^\s*(?:\d+\.)\s*(?=[A-Za-z])", "", s).strip()
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _finding_priority_rank(f: PromotedFinding) -> tuple[int, int]:
    """
    Lower is better. Adds within-category priority so plaintiff-useful structural findings beat generic variants.
    """
    label = (f.label or "").lower()
    cat = f.category
    if cat == "imaging":
        if _STRUCTURAL_IMAGING_PAT.search(label) and not any(p.search(label) for p in _NEGATIVE_IMAGING_PATTERNS):
            return (0, 0)
        if re.search(r"\b(spasm|straightening|lordosis)\b", label):
            return (1, 0)
        if any(p.search(label) for p in _NEGATIVE_IMAGING_PATTERNS):
            return (3, 0)
        return (2, 0)
    if cat == "objective_deficit":
        if re.search(r"\bnormal lordotic curvature\b", label):
            return (3, 0)
        if re.search(r"\b(weakness|diminished|[0-5]/5)\b", label):
            return (0, 0)
        if re.search(r"\b(spasm|straightening|lordosis)\b", label):
            return (1, 0)
        return (2, 0)
    return (0, 0)


def _sort_promoted_findings(items: list[PromotedFinding]) -> None:
    items.sort(
        key=lambda f: (
            _CATEGORY_ORDER.get(f.category, 99),
            0 if f.headline_eligible else 1,
            _finding_priority_rank(f)[0],
            {"high": 0, "medium": 1, "low": 2}.get(f.severity or "low", 2),
            -f.confidence,
            _finding_priority_rank(f)[1],
        )
    )


def _norm_region(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _norm_label(value: str) -> str:
    s = re.sub(r"\b(?:left|right|bilateral)\b", "", (value or "").lower())
    s = re.sub(r"\b(?:c\d-\s*c\d|c\d\d?|l\d-\s*l\d|l\d\d?)\b", "", s)
    s = re.sub(r"\b(?:mri|x-?ray|radiograph|impression|assessment|diagnosis)\b", "", s)
    s = re.sub(r"[^a-z0-9\s/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _semantic_finding_family_token(f: PromotedFinding) -> str:
    label = (f.label or "").lower()
    cat = f.category
    if cat == "objective_deficit":
        if re.search(r"\b(spasm|straightening|lordosis|loss of lordosis)\b", label):
            return "spasm_lordosis"
        if re.search(r"\b(weakness|strength|[0-5]/5)\b", label):
            return "strength_deficit"
        if re.search(r"\b(reflex|diminished reflex)\b", label):
            return "reflex_deficit"
        if re.search(r"\b(rom|range of motion)\b", label):
            return "rom_deficit"
        return "objective_other"
    if cat == "imaging":
        if any(p.search(label) for p in _NEGATIVE_IMAGING_PATTERNS):
            return "negative_imaging"
        if re.search(r"\b(spasm|straightening|lordosis|loss of lordosis)\b", label):
            return "spasm_lordosis"
        if re.search(r"\b(radicul)\b", label):
            return "radiculopathy"
        if re.search(r"\b(foramen|foraminal)\b", label):
            return "foraminal_pathology"
        if re.search(r"\b(stenosis)\b", label):
            return "stenosis"
        if re.search(r"\b(herniat|protrusion|bulg)\b", label):
            return "disc_pathology"
        if re.search(r"\b(disc)\b", label):
            return "disc_related"
        if re.search(r"\b(fracture|displacement|compression|tear)\b", label):
            return "structural_injury"
        return "imaging_other"
    if cat == "procedure":
        if re.search(r"\b(epidural|esi|injection)\b", label):
            return "injection"
        if re.search(r"\b(surgery|operative|arthroscop|fusion)\b", label):
            return "surgery"
        return "procedure_other"
    if cat == "visit_count":
        return "visit_count"
    if cat == "diagnosis":
        if re.search(r"\b(radicul)\b", label):
            return "dx_radiculopathy"
        if re.search(r"\b(strain|sprain)\b", label):
            return "dx_sprain_strain"
        if re.search(r"\b(disc|herniat|protrusion)\b", label):
            return "dx_disc"
        return "diagnosis_other"
    return f"{cat}_other"


def _finding_source_family(f: PromotedFinding) -> str:
    label = (f.label or "").lower()
    if not f.source_event_id:
        return "citation_fallback"
    if f.category == "imaging":
        return "imaging"
    if f.category == "procedure":
        return "procedure"
    if re.search(r"\b(physical therapy|pt\b|rom|range of motion|strength)\b", label):
        return "pt"
    return "clinical"


def _semantic_family_key(f: PromotedFinding) -> tuple[str, str, str, str]:
    return (
        str(f.category),
        _norm_region(f.body_region),
        str(f.finding_polarity or "neutral"),
        _semantic_finding_family_token(f),
    )


def _semantic_family_id(f: PromotedFinding) -> str:
    cat, region, polarity, fam = _semantic_family_key(f)
    return "|".join([cat or "unknown", region or "general", polarity or "neutral", fam or "other"])


def _labels_similar_within_family(a: PromotedFinding, b: PromotedFinding) -> bool:
    na = _norm_label(a.label)
    nb = _norm_label(b.label)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta = set(t for t in na.split() if len(t) >= 3)
    tb = set(t for t in nb.split() if len(t) >= 3)
    if ta and tb:
        jacc = len(ta & tb) / max(1, len(ta | tb))
        if jacc >= 0.78:
            return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.88


def _promoted_finding_pick_rank(f: PromotedFinding) -> tuple:
    return (
        0 if f.headline_eligible else 1,
        _CATEGORY_ORDER.get(f.category, 99),
        _finding_priority_rank(f)[0],
        {"high": 0, "medium": 1, "low": 2}.get(f.severity or "low", 2),
        -float(f.confidence or 0.0),
        -len(list(f.citation_ids or [])),
        len(f.label or ""),
    )


def _consolidate_promoted_findings(items: list[PromotedFinding]) -> list[PromotedFinding]:
    if not items:
        return []
    groups: list[list[PromotedFinding]] = []
    for f in items:
        placed = False
        fkey = _semantic_family_key(f)
        for group in groups:
            g0 = group[0]
            gkey = _semantic_family_key(g0)
            if gkey != fkey:
                continue
            # Some families (notably lordosis/spasm wording variants) should collapse on structured semantics
            # to avoid repeated headline clutter from minor phrasing changes.
            if gkey[3] != "spasm_lordosis" and not any(_labels_similar_within_family(f, g) for g in group):
                continue
            group.append(f)
            placed = True
            break
        if not placed:
            groups.append([f])

    consolidated: list[PromotedFinding] = []
    for group in groups:
        best = sorted(group, key=_promoted_finding_pick_rank)[0]
        citation_ids: list[str] = []
        seen_cids: set[str] = set()
        for g in group:
            for cid in list(g.citation_ids or []):
                scid = str(cid).strip()
                if not scid or scid in seen_cids:
                    continue
                seen_cids.add(scid)
                citation_ids.append(scid)
        source_families = sorted({_finding_source_family(g) for g in group})
        best = best.model_copy(update={
            "citation_ids": citation_ids[:12] if citation_ids else list(best.citation_ids or []),
            "confidence": max(float(g.confidence or 0.0) for g in group),
            "semantic_family": _semantic_family_id(best),
            "finding_source_count": len(group),
            "source_families": source_families,
        })
        consolidated.append(best)

    _sort_promoted_findings(consolidated)
    return consolidated


def _build_mechanism(events: list[Event]) -> RendererCitationValue:
    mechanism, _audit = _build_mechanism_from_events(events, None)
    return mechanism


def _mechanism_keywords_present(text: str) -> bool:
    return bool(re.search(r"\b(motor vehicle|collision|mva|mvc|rear[- ]end|crash|auto accident)\b", text or "", re.I))


def _mechanism_normalize_for_overlap(text: str) -> str:
    s = str(text or "").lower()
    s = re.sub(r"\b(mva|mvc)\b", "motor vehicle collision", s)
    s = re.sub(r"\bcar accident\b", "motor vehicle collision", s)
    s = re.sub(r"\bauto accident\b", "motor vehicle collision", s)
    s = re.sub(r"\bcrash\b", "collision", s)
    s = re.sub(r"\brear[- ]end(?:ed)?\b", "rear end collision", s)
    return s


def _mechanism_overlap_ratio(a: str, b: str) -> float:
    return _lexical_overlap_ratio(_mechanism_normalize_for_overlap(a), _mechanism_normalize_for_overlap(b))


def _mechanism_snippet_priority(snippet: str) -> int:
    sn = str(snippet or "").lower()
    if re.search(r"\b(hpi|history of present illness|chief complaint|presented with)\b", sn):
        return 0
    if re.search(r"\b(emergency department|emergency room|er visit|ed visit|trauma center)\b", sn):
        return 1
    if re.search(r"\b(initial evaluation|intake|initial consult|urgent care)\b", sn):
        return 2
    if re.search(r"\b(consult|orthopedic|neurology)\b", sn):
        return 3
    if re.search(r"\b(pt evaluation|physical therapy evaluation|plan of care)\b", sn):
        return 4
    return 5


def _mechanism_contradiction_penalty(label: str, snippet: str) -> int:
    low_label = (label or "").lower()
    low_sn = (snippet or "").lower()
    mva_like = bool(re.search(r"\b(motor vehicle|mvc|mva|rear[- ]end|collision|auto accident|car accident)\b", low_sn))
    fall_like = bool(re.search(r"\b(fall|trip and fall|slip and fall)\b", low_sn))
    work_like = bool(re.search(r"\b(work(?:place)? injury|on the job|lifting injury)\b", low_sn))
    if "motor vehicle" in low_label and (fall_like or work_like):
        return 1
    if "fall" in low_label and mva_like:
        return 1
    if "work injury" in low_label and mva_like:
        return 1
    return 0


_MECH_CITATION_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(rear[- ]end(?:ed)?)\b", re.I), "rear-end motor vehicle collision", "rear-end"),
    (re.compile(r"\b(motor vehicle collision|motor vehicle accident|mvc|mva|auto accident|car accident|collision|crash|impact)\b", re.I), "motor vehicle collision", "vehicle"),
    (re.compile(r"\b(slip and fall|trip and fall|ground[- ]level fall|glf|fall|fell|slipped|trip(?:ped)?)\b", re.I), "fall", "fall"),
    (re.compile(r"\b(pedestrian (?:struck|hit)|struck by vehicle|hit by vehicle|struck by)\b", re.I), "pedestrian struck", "struck_by"),
    (re.compile(r"\b(work(?:place)? injury|on the job|lifting injury|overexertion|twisting injury)\b", re.I), "work injury", "work"),
]


def _mechanism_is_negated(snippet: str, start_idx: int) -> bool:
    low = (snippet or "").lower()
    window = low[max(0, start_idx - 40): start_idx]
    return bool(re.search(r"\b(denies?|no|not|without|negative for)\b", window, re.I))


def _build_mechanism_from_citations_with_audit(citations: list[Citation] | None) -> tuple[RendererCitationValue, dict[str, Any]]:
    if not citations:
        return RendererCitationValue(value=None, citation_ids=[]), {
            "selected_label": None,
            "selected_citation_ids": [],
            "selected_candidate": None,
            "candidate_count": 0,
            "top_candidates": [],
        }
    candidates: list[dict[str, Any]] = []
    for c in citations:
        sn = _clean_citation_snippet_for_finding(str(getattr(c, "snippet", "") or "").strip())
        if not sn:
            continue
        for pat, label, trig in _MECH_CITATION_PATTERNS:
            m = pat.search(sn)
            if not m:
                continue
            if _mechanism_is_negated(sn, m.start()):
                continue
            sn_pri = _mechanism_snippet_priority(sn)
            score = 0
            score += 5 if sn_pri <= 1 else 3 if sn_pri <= 3 else 1
            score += 3 if label == "rear-end motor vehicle collision" else 0
            score += 2 if re.search(r"\b(today|yesterday|earlier today|\d{1,2}/\d{1,2}/\d{4}|20\d{2}-\d{2}-\d{2})\b", sn, re.I) else 0
            score += 2 if re.search(r"\b(neck|back|cervical|lumbar|shoulder|knee|head)\b", sn, re.I) else 0
            overlap = _mechanism_overlap_ratio(label, sn)
            if overlap < 0.20:
                continue
            candidates.append(
                {
                    "label": label,
                    "trigger": trig,
                    "citation_id": str(c.citation_id),
                    "page_number": int(getattr(c, "page_number", 999999) or 999999),
                    "snippet_priority": sn_pri,
                    "overlap": round(overlap, 4),
                    "score": score,
                }
            )
            break
    if not candidates:
        return RendererCitationValue(value=None, citation_ids=[]), {
            "selected_label": None,
            "selected_citation_ids": [],
            "selected_candidate": None,
            "candidate_count": 0,
            "top_candidates": [],
        }
    candidates.sort(
        key=lambda x: (
            -int(x.get("score", 0)),
            int(x.get("snippet_priority", 99)),
            -float(x.get("overlap", 0.0)),
            int(x.get("page_number", 999999)),
            str(x.get("citation_id", "")),
        )
    )
    best = candidates[0]
    return RendererCitationValue(value=str(best.get("label") or ""), citation_ids=[str(best.get("citation_id") or "")]), {
        "selected_label": str(best.get("label") or ""),
        "selected_citation_ids": [str(best.get("citation_id") or "")],
        "selected_candidate": best,
        "candidate_count": len(candidates),
        "top_candidates": candidates[:10],
    }


def _iso_date_to_obj(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        return date.fromisoformat(str(iso))
    except Exception:
        return None


def _build_mechanism_from_events(events: list[Event], citations: list[Citation] | None) -> tuple[RendererCitationValue, dict[str, Any]]:
    patterns = [
        (re.compile(r"\b(rear[- ]end)\b", re.I), "rear-end motor vehicle collision"),
        (re.compile(r"\b(motor vehicle collision|motor vehicle accident|mvc|mva|auto accident|car accident)\b", re.I), "motor vehicle collision"),
        (re.compile(r"\b(slip and fall|trip and fall|fall)\b", re.I), "fall"),
        (re.compile(r"\b(pedestrian (?:struck|hit)|struck by vehicle)\b", re.I), "pedestrian struck"),
        (re.compile(r"\b(motorcycle|bike accident|bicycle accident)\b", re.I), "vehicle collision"),
        (re.compile(r"\b(work(?:place)? injury|on the job|lifting injury)\b", re.I), "work injury"),
    ]
    cit_by_id = {str(c.citation_id): c for c in (citations or []) if str(getattr(c, "citation_id", "")).strip()}
    cits_by_page: dict[int, list[Citation]] = {}
    for c in (citations or []):
        try:
            pnum = int(getattr(c, "page_number", 0) or 0)
        except Exception:
            continue
        if pnum <= 0:
            continue
        cits_by_page.setdefault(pnum, []).append(c)
    doi_iso: str | None = None
    for e in events:
        s, _e = _iso_from_event(e)
        if s and (doi_iso is None or s < doi_iso):
            doi_iso = s
    doi_date = _iso_date_to_obj(doi_iso)
    candidates: list[dict[str, Any]] = []

    def _event_mech_priority(e: Event) -> tuple[int, str, str]:
        et = str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))).lower()
        blob = " ".join(_event_text_blobs(e)).lower()
        if et in {"er_visit", "hospital_admission"} and re.search(r"\b(hpi|history of present illness|chief complaint|presented with)\b", blob):
            p = 0
        elif et in {"er_visit", "hospital_admission"}:
            p = 1
        elif re.search(r"\b(initial evaluation|intake|initial consult|urgent care)\b", blob):
            p = 2
        elif re.search(r"\b(consult|orthopedic)\b", blob):
            p = 3
        elif re.search(r"\b(pt evaluation|physical therapy evaluation|plan of care)\b", blob):
            p = 4
        else:
            p = 5
        return (p, _iso_from_event(e)[0] or "9999-99-99", str(getattr(e, "event_id", "")))

    ordered = sorted(events, key=_event_mech_priority)
    for e in ordered:
        blob = " ".join(_event_text_blobs(e)).lower()
        if not blob:
            continue
        event_date_iso = _iso_from_event(e)[0]
        event_date = _iso_date_to_obj(event_date_iso)
        for pat, label in patterns:
            if pat.search(blob):
                event_cids = [str(c) for c in (getattr(e, "citation_ids", []) or []) if str(c).strip()]
                scored_strong: list[tuple[int, int, int, float, int, str, str]] = []
                for cid in event_cids:
                    c = cit_by_id.get(cid)
                    sn = _clean_citation_snippet_for_finding(str(getattr(c, "snippet", "") or "").strip()) if c else ""
                    if not sn or not _mechanism_keywords_present(sn):
                        continue
                    overlap = _mechanism_overlap_ratio(label, sn)
                    if overlap < 0.20:
                        continue
                    page_no = int(getattr(c, "page_number", 999999) or 999999) if c else 999999
                    event_pri = _event_mech_priority(e)[0]
                    snippet_pri = _mechanism_snippet_priority(sn)
                    contrad = _mechanism_contradiction_penalty(label, sn)
                    doi_dist = abs((event_date - doi_date).days) if (event_date and doi_date) else 99999
                    scored_strong.append((event_pri, snippet_pri, contrad, -overlap, doi_dist, page_no, cid))
                if not scored_strong:
                    for pnum in sorted(set(getattr(e, "source_page_numbers", []) or [])):
                        page_cands = cits_by_page.get(int(pnum), [])
                        scored_page_cands: list[tuple[int, int, int, float, int, str, str]] = []
                        for pc in page_cands:
                            sn = _clean_citation_snippet_for_finding(str(getattr(pc, "snippet", "") or "").strip())
                            if not sn or not _mechanism_keywords_present(sn):
                                continue
                            overlap = _mechanism_overlap_ratio(label, sn)
                            if overlap < 0.20:
                                continue
                            event_pri = _event_mech_priority(e)[0]
                            pri = _mechanism_snippet_priority(sn)
                            contrad = _mechanism_contradiction_penalty(label, sn)
                            doi_dist = abs((event_date - doi_date).days) if (event_date and doi_date) else 99999
                            scored_page_cands.append((event_pri, pri, contrad, -overlap, doi_dist, int(getattr(pc, "page_number", 999999) or 999999), str(pc.citation_id)))
                        if scored_page_cands:
                            scored_page_cands.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4], t[5], t[6]))
                            scored_strong = scored_page_cands[:3]
                            break
                if scored_strong:
                    scored_strong.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4], t[5], t[6]))
                strong_cids = [cid for _event_pri, _pri, _contrad, _neg_ov, _doi_dist, _pg, cid in scored_strong]
                for event_pri, pri, contrad, neg_ov, doi_dist, pg, cid in scored_strong[:5]:
                    candidates.append(
                        {
                            "label": label,
                            "event_id": str(getattr(e, "event_id", "") or ""),
                            "citation_id": cid,
                            "event_priority": event_pri,
                            "snippet_priority": pri,
                            "contradiction_penalty": contrad,
                            "overlap": round(-neg_ov, 4),
                            "doi_distance_days": doi_dist,
                            "page_number": pg,
                        }
                    )
                cids = strong_cids or event_cids
                if cids and (not strong_cids and citations):
                    # If we have citations loaded, avoid weak mechanism citations without mechanism keywords.
                    continue
                if cids:
                    cands_for_label = [c for c in candidates if c["label"] == label]
                    best_cand = sorted(
                        cands_for_label,
                        key=lambda x: (
                            int(x.get("event_priority", 99)),
                            int(x.get("snippet_priority", 99)),
                            int(x.get("contradiction_penalty", 99)),
                            -float(x.get("overlap", 0.0)),
                            int(x.get("doi_distance_days", 99999)),
                            int(x.get("page_number", 999999)),
                            str(x.get("citation_id", "")),
                        ),
                    )[0] if cands_for_label else None
                    audit = {
                        "selected_label": label,
                        "selected_citation_ids": cids[:8],
                        "selected_candidate": best_cand,
                        "candidate_count": len(candidates),
                        "top_candidates": sorted(
                            candidates,
                            key=lambda x: (
                                int(x.get("event_priority", 99)),
                                int(x.get("snippet_priority", 99)),
                                int(x.get("contradiction_penalty", 99)),
                                -float(x.get("overlap", 0.0)),
                                int(x.get("doi_distance_days", 99999)),
                                int(x.get("page_number", 999999)),
                                str(x.get("citation_id", "")),
                            ),
                        )[:10],
                    }
                    return RendererCitationValue(value=label, citation_ids=cids[:8]), audit
    return RendererCitationValue(value=None, citation_ids=[]), {
        "selected_label": None,
        "selected_citation_ids": [],
        "selected_candidate": None,
        "candidate_count": len(candidates),
        "top_candidates": sorted(
            candidates,
            key=lambda x: (
                int(x.get("event_priority", 99)),
                int(x.get("snippet_priority", 99)),
                int(x.get("contradiction_penalty", 99)),
                -float(x.get("overlap", 0.0)),
                int(x.get("doi_distance_days", 99999)),
                int(x.get("page_number", 999999)),
                str(x.get("citation_id", "")),
            ),
        )[:10],
    }


def _build_mechanism_from_citations(citations: list[Citation] | None) -> RendererCitationValue:
    mech, _audit = _build_mechanism_from_citations_with_audit(citations)
    return mech


def _build_pt_summary(events: list[Event], citations: list[Citation] | None = None, ext: dict[str, Any] | None = None) -> RendererPtSummary:
    ext = ext or {}
    pt_encounters = [r for r in (ext.get("pt_encounters") or []) if isinstance(r, dict) and str(r.get("source") or "primary") == "primary"]
    pt_reported = [r for r in (ext.get("pt_count_reported") or []) if isinstance(r, dict)]
    if pt_encounters or pt_reported:
        verified_count = len(pt_encounters)
        starts = [str(r.get("encounter_date") or "") for r in pt_encounters if str(r.get("encounter_date") or "").strip() and str(r.get("encounter_date")) not in _SENTINEL_DATES]
        ends = list(starts)
        citation_ids_collected: list[str] = []
        for row in pt_encounters + pt_reported:
            for cid in list(row.get("evidence_citation_ids") or []):
                scid = str(cid).strip()
                if scid and scid not in citation_ids_collected:
                    citation_ids_collected.append(scid)
        reported_vals = sorted({int(r.get("reported_count") or 0) for r in pt_reported if int(r.get("reported_count") or 0) > 0})
        cmin = min(reported_vals) if reported_vals else None
        cmax = max(reported_vals) if reported_vals else None
        note = None
        if cmin is not None and cmax is not None and (cmin != verified_count or cmax != verified_count):
            if cmin != cmax:
                note = (
                    f"Reported PT totals in records vary ({cmin}-{cmax}). "
                    f"Verified PT count is {verified_count} based on enumerated dated encounters in this packet."
                )
            else:
                note = (
                    f"Reported PT total in records: {cmax}. "
                    f"Verified PT count is {verified_count} based on enumerated dated encounters in this packet."
                )
        return RendererPtSummary(
            total_encounters=verified_count,
            encounter_count_min=cmin,
            encounter_count_max=cmax,
            date_start=min(starts) if starts else None,
            date_end=max(ends) if ends else None,
            discharge_status=None,
            reconciliation_note=note,
            citation_ids=citation_ids_collected[:12],
            count_source="event_count",
        )

    pt_evidence_events: list[Event] = []
    for e in events:
        etype = str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", "")))
        blobs = _event_text_blobs(e)
        joined = " ".join(blobs).lower()
        if etype == "pt_visit" or ("physical therapy" in joined or re.search(r"\bpt\b", joined)):
            pt_evidence_events.append(e)
    if not pt_evidence_events:
        return RendererPtSummary(count_source="not_found")

    aggregate_counts: list[int] = []
    citation_ids_collected: list[str] = []
    starts: list[str] = []
    ends: list[str] = []
    discharge_status: str | None = None

    for e in pt_evidence_events:
        for cid in list(getattr(e, "citation_ids", []) or []):
            if cid not in citation_ids_collected:
                citation_ids_collected.append(cid)
        s, en = _iso_from_event(e)
        if s:
            starts.append(s)
        if en:
            ends.append(en)

        for txt in _event_text_blobs(e):
            m = re.search(r"\b(?:PT sessions documented|Aggregated PT sessions)\D+(\d+)\s+encounters?\b", txt, re.I)
            if m:
                aggregate_counts.append(int(m.group(1)))
            elif (m2 := re.search(r"\bPT sessions documented:\s*(\d+)\b", txt, re.I)):
                aggregate_counts.append(int(m2.group(1)))
            if "discharge" in txt.lower() and not discharge_status:
                discharge_status = txt[:180]

    # Expand PT date span using PT-event citation snippets when event dates are missing/sentinel.
    if citations and citation_ids_collected:
        cit_by_id = {str(c.citation_id): c for c in citations}
        for cid in citation_ids_collected:
            c = cit_by_id.get(str(cid))
            if not c:
                continue
            sn = str(getattr(c, "snippet", "") or "")
            if not sn:
                continue
            for mm, dd, yyyy in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", sn):
                try:
                    d = datetime(int(yyyy), int(mm), int(dd)).date().isoformat()
                except Exception:
                    continue
                if d not in _SENTINEL_DATES:
                    starts.append(d)
                    ends.append(d)
            for iso in re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", sn):
                if iso not in _SENTINEL_DATES:
                    starts.append(iso)
                    ends.append(iso)

    # Citation-backed fallback for aggregate summaries that were not promoted into event facts.
    if citations:
        for c in citations:
            sn = str(getattr(c, "snippet", "") or "")
            low = sn.lower()
            if "physical therapy" not in low and "pt " not in f" {low} " and "pt sessions" not in low and "aggregated pt sessions" not in low:
                continue
            m = re.search(r"\b(?:PT sessions documented|Aggregated PT sessions)\D+(\d+)\s+encounters?\b", sn, re.I)
            if m:
                aggregate_counts.append(int(m.group(1)))

    if aggregate_counts:
        total = max(aggregate_counts)
        source = "aggregate_snippet"
    else:
        total = sum(1 for e in pt_evidence_events if str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))) == "pt_visit")
        total = total or len(pt_evidence_events)
        source = "event_count"
    unique_counts = sorted({c for c in aggregate_counts if c > 0})
    note = None
    cmin = min(unique_counts) if unique_counts else None
    cmax = max(unique_counts) if unique_counts else None
    dated_pt_count = sum(
        1
        for e in pt_evidence_events
        if str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", ""))) == "pt_visit"
        and _iso_from_event(e)[0] is not None
    )
    if cmin is not None and cmax is not None and cmin != cmax:
        note = (
            f"Treatment volume varies across records ({cmin}-{cmax} sessions). "
            f"Chronology verifies {dated_pt_count} dated treatment sessions. "
            f"Documentation indicates a total range of {cmin}-{cmax} visits; "
            f"the maximum reported intensity is reflected here for clinical completeness."
        )
    elif cmax is not None and dated_pt_count and dated_pt_count != cmax:
        note = (
            f"Chronology verifies {dated_pt_count} dated treatment sessions; "
            f"aggregate clinical records report {cmax} total sessions. "
            f"This summary uses the aggregate-reported count for treatment-intensity reference."
        )

    return RendererPtSummary(
        total_encounters=total,
        encounter_count_min=cmin,
        encounter_count_max=cmax,
        date_start=min(starts) if starts else None,
        date_end=max(ends) if ends else None,
        discharge_status=discharge_status,
        reconciliation_note=clean_meta_language(note),
        citation_ids=citation_ids_collected[:12],
        count_source=source,
    )


def _promoted_findings_from_citations(
    citations: list[Citation] | None,
    existing: list[PromotedFinding],
) -> list[PromotedFinding]:
    if not citations:
        return existing
    seen = {f"{pf.category}|{pf.label.strip().lower()}" for pf in existing}
    have_categories = {pf.category for pf in existing if pf.headline_eligible}
    out = list(existing)
    have_positive_imaging = any(
        pf.category == "imaging" and pf.headline_eligible and (pf.finding_polarity != "negative")
        and re.search(r"\b(disc|foramen|foraminal|radicul|stenosis|herniat|protrusion|compression|displacement)\b", pf.label, re.I)
        and not any(p.search(pf.label) for p in _NEGATIVE_IMAGING_PATTERNS)
        for pf in existing
    )

    def add(category: str, label: str, citation_id: str, *, severity: str = "high", headline: bool = True, polarity: str | None = None):
        key = f"{category}|{label.strip().lower()}"
        if key in seen:
            return
        clean_lbl = clean_meta_language(label.strip())
        if not clean_lbl:
            return
        seen.add(key)
        out.append(PromotedFinding(
            category=category,
            label=clean_lbl,
            severity=severity, headline_eligible=headline, finding_polarity=polarity,
            is_verbatim=True,
            citation_ids=[citation_id],
            confidence=0.75 if headline else 0.55,
        ))

    # Only fallback-fill missing critical categories to avoid overfitting/duplication.
    need_dx = "diagnosis" not in have_categories
    need_obj = "objective_deficit" not in have_categories
    need_proc = "procedure" not in have_categories
    need_img = "imaging" not in have_categories

    for c in sorted(citations, key=lambda x: int(getattr(x, "page_number", 999999) or 999999)):
        sn = _clean_finding_label(str(getattr(c, "snippet", "") or "").strip())
        if not sn:
            continue
        if any(p.search(sn) for p in _GENERIC_PLACEHOLDER_PATTERNS):
            continue
        if is_fax_header_noise(sn):
            continue
        # Generic diagnosis fallback: ICD-coded diagnosis lines
        if need_dx and re.search(r"\bICD-10\b", sn, re.I):
            if re.search(r"\b([A-TV-Z]\d{1,2}(?:\.\d+)?)\b", sn):
                add("diagnosis", sn, str(c.citation_id), severity="high", headline=True, polarity="positive")
                continue
        # Generic procedure/intervention fallback
        if need_proc and re.search(r"\b(injection|epidural|surgery|operative|arthroscop|fusion|procedure performed)\b", sn, re.I):
            add("procedure", sn, str(c.citation_id), severity="high", headline=True, polarity="positive")
            continue
        # PT aggregate counts belong in visit_count, not objective findings.
        if re.search(r"\b(?:aggregated pt sessions?|pt sessions documented)\b", sn, re.I):
            if re.search(r"\b\d+\s+encounters?\b", sn, re.I):
                add("visit_count", sn, str(c.citation_id), severity="medium", headline=True, polarity="neutral")
            continue
        # Generic objective-deficit fallback
        if need_obj and re.search(r"\b(weakness|strength|reflex|diminished|range of motion|rom|spasm|lordosis|[0-5]/5)\b", sn, re.I):
            sn = _best_objective_clause(sn)
            if re.search(r"\bnormal lordotic curvature\b", sn, re.I):
                continue
            if re.search(r"\bnormal\b", sn, re.I) and re.search(r"\bno evidence\b", sn, re.I):
                continue
            if re.search(r"\b(normal|maintained)\b", sn, re.I) and not re.search(r"\b(weakness|diminished|spasm|straightening|loss of lordosis|[0-5]/5)\b", sn, re.I):
                continue
            # avoid pure headers/labels
            if not re.fullmatch(r"[A-Za-z0-9 /:+().-]{1,40}", sn.strip()):
                add("objective_deficit", sn, str(c.citation_id), severity="high", headline=True, polarity="positive")
                continue
        # Generic imaging pathology fallback (positive structural findings only)
        if (need_img or not have_positive_imaging) and re.search(r"\b(disc|foramen|foraminal|stenosis|herniat|protrusion|tear|edema|compression|fracture|displacement)\b", sn, re.I):
            negative = bool(any(p.search(sn) for p in _NEGATIVE_IMAGING_PATTERNS))
            add("imaging", sn, str(c.citation_id), severity=("low" if negative else "high"), headline=(not negative), polarity=("negative" if negative else "positive"))
            if not negative:
                have_positive_imaging = True
            continue

    _sort_promoted_findings(out)
    return out


def _claim_to_category(claim_type: str) -> str:
    if claim_type == "IMAGING_FINDING":
        return "imaging"
    if claim_type == "INJURY_DX":
        return "diagnosis"
    if claim_type == "PROCEDURE":
        return "procedure"
    if claim_type == "TREATMENT_VISIT":
        return "treatment"
    if claim_type == "SYMPTOM":
        return "symptom"
    return "symptom"


def _claim_to_polarity_and_headline(assertion: str, flags: list[str], category: str) -> tuple[str | None, bool]:
    flags_l = {str(f).lower() for f in (flags or [])}
    a = (assertion or "").lower()
    if any(p.search(a) for p in _GENERIC_PLACEHOLDER_PATTERNS):
        return ("neutral", False)
    negative = bool(
        ("degenerative_language" in flags_l)
        or any(p.search(a) for p in _NEGATIVE_IMAGING_PATTERNS)
    )
    if negative:
        return ("negative", False)
    if category in {"objective_deficit", "imaging", "diagnosis", "procedure"}:
        return ("positive", True)
    return ("neutral", True)


def _promoted_findings_from_claim_rows(claim_rows: list[dict[str, Any]]) -> list[PromotedFinding]:
    out: list[PromotedFinding] = []
    seen_keys: set[str] = set()
    for row in claim_rows or []:
        citations = [str(c) for c in (row.get("citations") or []) if str(c).strip()]
        if not citations:
            continue
        assertion = _clean_finding_label(str(row.get("assertion") or "").strip())
        if not assertion:
            continue
        if any(p.search(assertion) for p in _GENERIC_PLACEHOLDER_PATTERNS):
            continue
        if is_fax_header_noise(assertion):
            continue
        claim_type = str(row.get("claim_type") or "")
        category = _claim_to_category(claim_type)
        # Promote clear objective deficits separately when claim rows call them dx/symptom.
        if re.search(r"\bnormal lordotic curvature\b", assertion, re.I):
            category = "imaging"
        if re.search(r"\b(?:4/5|weakness|strength|range of motion|rom)\b", assertion, re.I) and not re.search(r"\b(?:aggregated pt sessions?|encounters?)\b", assertion, re.I):
            category = "objective_deficit"
            assertion = _best_objective_clause(assertion)
        if re.search(r"\bvisits?\b|\bencounters?\b", assertion, re.I):
            category = "visit_count"
        polarity, headline = _claim_to_polarity_and_headline(assertion, list(row.get("flags") or []), category)
        key = f"{category}|{assertion.lower()}"
        if key in seen_keys:
            continue
        support_score = row.get("support_score")
        selection_score = row.get("selection_score")
        if _is_low_value_claim_for_promotion(
            assertion,
            category=category,
            claim_type=claim_type,
            support_score=support_score,
            selection_score=selection_score,
        ):
            continue
        seen_keys.add(key)
        conf = 0.0
        if isinstance(selection_score, (int, float)):
            conf = max(conf, min(1.0, float(selection_score) / 100.0))
        if isinstance(support_score, (int, float)):
            conf = max(conf, min(1.0, float(support_score) / 5.0))
        severity = "high" if category in {"objective_deficit", "imaging", "diagnosis", "procedure"} and headline else ("low" if not headline else "medium")
        is_verbatim = "VERBATIM" in {str(f).upper() for f in (row.get("flags") or [])}
        clean_label = clean_meta_language(assertion)
        if not clean_label:
            continue
        out.append(PromotedFinding(
            category=category, label=clean_label, body_region=(row.get("body_region") or None),
            severity=severity, headline_eligible=headline, finding_polarity=polarity,
            is_verbatim=is_verbatim,
            citation_ids=citations, confidence=conf, source_event_id=str(row.get("event_id") or "") or None
        ))

    _sort_promoted_findings(out)
    return out


def _gate_tokens(text: str) -> set[str]:
    toks = {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 2}
    return {t for t in toks if t not in _CLAIM_GATE_STOPWORDS}


def _lexical_overlap_ratio(a: str, b: str) -> float:
    ta = _gate_tokens(a)
    tb = _gate_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta))


def _normalize_promoted_citation_ids_with_hard_gate(
    promoted: list[PromotedFinding],
    citations: list[Citation] | None,
) -> list[PromotedFinding]:
    if not promoted or not citations:
        return promoted

    by_id = {str(c.citation_id): c for c in citations if str(getattr(c, "citation_id", "")).strip()}
    by_page: dict[int, list[Citation]] = {}
    for c in citations:
        try:
            pno = int(getattr(c, "page_number", 0) or 0)
        except Exception:
            continue
        if pno <= 0:
            continue
        by_page.setdefault(pno, []).append(c)
    for rows in by_page.values():
        rows.sort(key=lambda c: str(getattr(c, "citation_id", "")))

    gated: list[PromotedFinding] = []
    for pf in promoted:
        resolved: list[Citation] = []
        for raw in list(pf.citation_ids or []):
            s = str(raw or "").strip()
            if not s:
                continue
            if s in by_id:
                resolved.append(by_id[s])
                continue
            m = re.match(r"(?i)^p\.\s*(\d+)$", s)
            if m:
                page_no = int(m.group(1))
                resolved.extend(by_page.get(page_no, []))

        if not resolved:
            continue  # Hard gate: no indexed citation text backing

        # Prefer citations whose snippets lexically overlap the claim text.
        ranked: list[tuple[float, Citation]] = []
        for c in resolved:
            snip = str(getattr(c, "snippet", "") or "").strip()
            if not snip:
                continue
            overlap = _lexical_overlap_ratio(pf.label, snip)
            ranked.append((overlap, c))
        ranked.sort(key=lambda x: (x[0], str(getattr(x[1], "citation_id", ""))), reverse=True)
        if not ranked:
            continue  # Hard gate: citation ids exist but no OCR/snippet text

        min_overlap = 0.15 if pf.category in {"imaging", "diagnosis", "objective_deficit", "procedure"} else 0.10
        best_overlap = ranked[0][0]
        if best_overlap < min_overlap:
            continue  # Hard gate: claim text not lexically supported by cited OCR snippets

        out_ids: list[str] = []
        seen: set[str] = set()
        for overlap, c in ranked:
            cid = str(getattr(c, "citation_id", "") or "").strip()
            if not cid or cid in seen:
                continue
            # Keep a small set, but require at least one citation meeting threshold.
            if overlap < min_overlap and out_ids:
                continue
            seen.add(cid)
            out_ids.append(cid)
            if len(out_ids) >= 8:
                break
        if not out_ids:
            continue
        gated.append(pf.model_copy(update={"citation_ids": out_ids}))
    return gated


def _promoted_findings_from_events(events: list[Event], existing: list[PromotedFinding]) -> list[PromotedFinding]:
    seen = {f"{pf.category}|{pf.label.strip().lower()}" for pf in existing}
    out: list[PromotedFinding] = list(existing)
    for e in events:
        event_cids = [str(c) for c in (getattr(e, "citation_ids", []) or []) if str(c).strip()]
        if not event_cids:
            continue
        pools: list[tuple[str, list[Any], str | None]] = [
            ("diagnosis", list(getattr(e, "diagnoses", []) or []), None),
            ("objective_deficit", list(getattr(e, "exam_findings", []) or []), None),
            ("procedure", list(getattr(e, "procedures", []) or []), None),
            ("treatment", list(getattr(e, "treatment_plan", []) or []), None),
        ]
        imaging = getattr(e, "imaging", None)
        if imaging and getattr(imaging, "impression", None):
            body_part = str(getattr(imaging, "body_part", "") or "").strip() or None
            pools.append(("imaging", list(getattr(imaging, "impression", []) or []), body_part))
        for category, facts, body_region in pools:
            for fact in facts:
                fact_category = category
                txt = _clean_finding_label(str(getattr(fact, "text", "") or "").strip())
                if not txt or getattr(fact, "technical_noise", False):
                    continue
                if is_fax_header_noise(txt):
                    continue
                citation_ids = [str(c) for c in (getattr(fact, "citation_ids", []) or []) if str(c).strip()] or event_cids
                if not citation_ids:
                    continue
                if any(p.search(txt) for p in _GENERIC_PLACEHOLDER_PATTERNS):
                    continue
                if re.search(r"\b(?:aggregated pt sessions?|pt sessions documented)\b", txt, re.I):
                    fact_category = "visit_count"
                claim_type_hint = {
                    "diagnosis": "INJURY_DX",
                    "procedure": "PROCEDURE",
                    "treatment": "TREATMENT_VISIT",
                    "objective_deficit": "SYMPTOM",
                    "imaging": "IMAGING_FINDING",
                }.get(fact_category, "")
                if _is_low_value_claim_for_promotion(
                    txt,
                    category=fact_category,
                    claim_type=claim_type_hint,
                    support_score=None,
                    selection_score=getattr(e, "confidence", 0),
                ):
                    continue
                # objective deficits are elevated by source field; generic pain-only exam items are not headline-worthy
                polarity, headline = _claim_to_polarity_and_headline(txt, list(getattr(e, "flags", []) or []), fact_category)
                if fact_category == "objective_deficit":
                    if re.search(r"\bnormal lordotic curvature\b", txt, re.I):
                        headline = False
                        polarity = "neutral"
                    if re.search(r"\bpain\b", txt, re.I) and not re.search(r"\b(weakness|strength|reflex|rom|lordosis|spasm|4/5|diminished)\b", txt, re.I):
                        headline = False
                    if re.search(r"\bnormal\b", txt, re.I) and re.search(r"\bno evidence\b", txt, re.I):
                        headline = False
                        polarity = "neutral"
                    if re.search(r"\b(normal|maintained)\b", txt, re.I) and not re.search(r"\b(weakness|diminished|spasm|straightening|loss of lordosis|4/5)\b", txt, re.I):
                        headline = False
                        polarity = "neutral"
                key = f"{fact_category}|{txt.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                severity = "high" if fact_category in {"objective_deficit", "imaging", "diagnosis", "procedure"} and headline else ("low" if not headline else "medium")
                eid = str(getattr(e, "event_id", "") or "").strip() or None
                is_verbatim = bool(getattr(fact, "verbatim", False))
                clean_txt = clean_meta_language(txt)
                if not clean_txt:
                    continue
                out.append(PromotedFinding(
                    category=fact_category,
                    label=clean_txt,
                    body_region=body_region,
                    severity=severity,
                    headline_eligible=headline,
                    finding_polarity=polarity,
                    is_verbatim=is_verbatim,
                    citation_ids=citation_ids[:8],
                    confidence=min(1.0, float(getattr(e, "confidence", 0) or 0) / 100.0),
                    source_event_id=eid,
                ))
        # Snapshot Expansion v2: harvest additional structured symptom/treatment/objective facts
        # from already-cited event text without introducing new extraction.
        harvest_lines: list[tuple[str, bool]] = []
        for val in (getattr(e, "chief_complaint", None), getattr(e, "reason_for_visit", None)):
            txt = _clean_finding_label(str(val or "").strip())
            if txt:
                harvest_lines.append((txt, False))
        for fact in list(getattr(e, "facts", []) or []) + list(getattr(e, "medications", []) or []):
            if getattr(fact, "technical_noise", False):
                continue
            txt = _clean_finding_label(str(getattr(fact, "text", "") or "").strip())
            if not txt:
                continue
            harvest_lines.append((txt, bool(getattr(fact, "verbatim", False))))

        for txt, is_verbatim in harvest_lines:
            if any(p.search(txt) for p in _GENERIC_PLACEHOLDER_PATTERNS):
                continue
            clean_txt = clean_meta_language(txt)
            if not clean_txt:
                continue
            category = "symptom"
            if _SNAP_MEDS_PAT.search(clean_txt):
                category = "treatment"
            elif _SNAP_ROM_PAT.search(clean_txt):
                category = "objective_deficit"
            elif _STRUCTURAL_IMAGING_PAT.search(clean_txt):
                category = "imaging"
            elif re.search(r"\b(icd-?10|radiculopathy|strain|sprain|diagnosis)\b", clean_txt, re.I):
                category = "diagnosis"
            elif _SNAP_DISPO_PAT.search(clean_txt):
                category = "treatment"
            claim_type_hint = {
                "diagnosis": "INJURY_DX",
                "treatment": "TREATMENT_VISIT",
                "objective_deficit": "SYMPTOM",
                "imaging": "IMAGING_FINDING",
                "symptom": "SYMPTOM",
            }.get(category, "")
            if _is_low_value_claim_for_promotion(
                clean_txt,
                category=category,
                claim_type=claim_type_hint,
                support_score=None,
                selection_score=getattr(e, "confidence", 0),
            ):
                continue
            polarity, headline = _claim_to_polarity_and_headline(clean_txt, list(getattr(e, "flags", []) or []), category)
            if not (
                _SNAP_NUMERIC_PAT.search(clean_txt)
                or _SNAP_PAIN_PAT.search(clean_txt)
                or _SNAP_VITALS_PAT.search(clean_txt)
                or _SNAP_ROM_PAT.search(clean_txt)
                or _SNAP_MEDS_PAT.search(clean_txt)
            ):
                continue
            key = f"{category}|{clean_txt.lower()}"
            if key in seen:
                continue
            seen.add(key)
            severity = "high" if category in {"objective_deficit", "imaging", "diagnosis", "procedure"} and headline else ("low" if not headline else "medium")
            eid = str(getattr(e, "event_id", "") or "").strip() or None
            out.append(
                PromotedFinding(
                    category=category,
                    label=clean_txt,
                    body_region=None,
                    severity=severity,
                    headline_eligible=headline,
                    finding_polarity=polarity,
                    is_verbatim=is_verbatim,
                    citation_ids=event_cids[:8],
                    confidence=min(1.0, float(getattr(e, "confidence", 0) or 0) / 100.0),
                    source_event_id=eid,
                )
            )
    _sort_promoted_findings(out)
    return out


def _top_case_drivers_from_claim_rows(claim_rows: list[dict[str, Any]]) -> list[str]:
    def _is_low_value_top_driver(assertion: str, claim_type: str, row: dict[str, Any]) -> bool:
        cat = _claim_to_category(claim_type)
        if re.search(r"\b(?:4/5|weakness|strength|reflex|rom)\b", assertion, re.I):
            cat = "objective_deficit"
        if _is_low_value_claim_for_promotion(
            assertion,
            category=cat,
            claim_type=claim_type,
            support_score=row.get("support_score"),
            selection_score=row.get("selection_score"),
        ):
            return True
        if claim_type == "TREATMENT_VISIT" and re.search(r"\baggregated pt sessions?\b", assertion, re.I):
            return True
        if claim_type == "TREATMENT_VISIT" and re.search(r"\btotal amount:\s*[$]?\d", assertion, re.I):
            return True
        if claim_type == "IMAGING_FINDING" and any(p.search(assertion) for p in _NEGATIVE_IMAGING_PATTERNS):
            return True
        return False

    def _row_rank(r: dict[str, Any]) -> tuple:
        ctype = str(r.get("claim_type") or "")
        cat = _claim_to_category(ctype)
        assertion = str(r.get("assertion") or "")
        if re.search(r"\b(?:4/5|weakness|strength|reflex|rom)\b", assertion, re.I):
            cat = "objective_deficit"
        pol, headline = _claim_to_polarity_and_headline(assertion, list(r.get("flags") or []), cat)
        generic = any(p.search(assertion) for p in _GENERIC_PLACEHOLDER_PATTERNS)
        return (
            _CATEGORY_ORDER.get(cat, 99),
            0 if headline else 1,
            1 if generic else 0,
            -(int(r.get("selection_score") or 0)),
            -(int(r.get("support_score") or 0)),
            str(r.get("date") or "9999-99-99"),
            1 if pol == "negative" else 0,
        )

    ranked = sorted(
        [
            r for r in (claim_rows or [])
            if r.get("event_id")
            and (r.get("citations") or [])
            and not _is_low_value_top_driver(str(r.get("assertion") or ""), str(r.get("claim_type") or ""), r)
        ],
        key=_row_rank,
    )
    out: list[str] = []
    seen: set[str] = set()
    for r in ranked:
        eid = str(r.get("event_id"))
        if eid in seen:
            continue
        seen.add(eid)
        out.append(eid)
        if len(out) >= 10:
            break
    return out


def _top_case_driver_fallback_from_events(events: list[Event], existing_ids: list[str]) -> list[str]:
    """
    Low-risk fallback for Top-10 parity: return citation-backed event IDs only.
    Keeps the existing manifest contract (`top_case_drivers` as event IDs).
    """
    seen = {str(eid).strip() for eid in (existing_ids or []) if str(eid).strip()}
    out = list(existing_ids or [])

    def _score(e: Event) -> tuple[int, str, str]:
        et = str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", "")) or "").lower()
        txt = " ".join(_event_text_blobs(e)).lower()
        score = 0
        if et in {"er_visit", "hospital_admission"}:
            score += 4
        if getattr(e, "imaging", None):
            score += 3
        if getattr(e, "procedures", None):
            score += 3
        if getattr(e, "exam_findings", None):
            score += 2
        if getattr(e, "diagnoses", None):
            score += 2
        if re.search(r"\b(discharge|procedure|impression|assessment)\b", txt):
            score += 1
        if re.search(r"\b(follow-?up only|routine)\b", txt):
            score -= 1
        return (-score, _iso_from_event(e)[0] or "9999-99-99", str(getattr(e, "event_id", "")))

    for e in sorted(events, key=_score):
        eid = str(getattr(e, "event_id", "") or "").strip()
        if not eid or eid in seen:
            continue
        if not [str(c).strip() for c in (getattr(e, "citation_ids", []) or []) if str(c).strip()]:
            continue
        candidate_blobs = [b.strip() for b in _event_text_blobs(e) if b and b.strip()]
        substantive_blobs: list[str] = []
        for txt in candidate_blobs:
            low = txt.lower()
            category = "symptom"
            claim_type_hint = "SYMPTOM"
            if _STRUCTURAL_IMAGING_PAT.search(txt):
                category = "imaging"
                claim_type_hint = "IMAGING_FINDING"
            elif re.search(r"\b(icd-?10|radiculopathy|strain|sprain|diagnosis|fracture|herniat|stenosis)\b", txt, re.I):
                category = "diagnosis"
                claim_type_hint = "INJURY_DX"
            elif _SNAP_ROM_PAT.search(txt):
                category = "objective_deficit"
                claim_type_hint = "SYMPTOM"
            elif _SNAP_MEDS_PAT.search(txt) or _SUBSTANTIVE_TREATMENT_RE.search(txt):
                category = "treatment"
                claim_type_hint = "TREATMENT_VISIT"
            if _is_low_value_claim_for_promotion(
                txt,
                category=category,
                claim_type=claim_type_hint,
                support_score=None,
                selection_score=getattr(e, "confidence", 0),
            ):
                continue
            if any(p.search(low) for p in _GENERIC_PLACEHOLDER_PATTERNS):
                continue
            substantive_blobs.append(txt)
        txt = " ".join(substantive_blobs).strip()
        if not txt:
            continue
        seen.add(eid)
        out.append(eid)
        if len(out) >= 10:
            break
    return out


def _build_bucket_evidence(events: list[Event], citations: list[Citation] | None = None) -> dict[str, BucketEvidence]:
    buckets: dict[str, BucketEvidence] = {
        "ed": BucketEvidence(),
        "pt_eval": BucketEvidence(),
    }
    citation_by_id = {
        str(getattr(c, "citation_id", "")).strip(): c
        for c in (citations or [])
        if str(getattr(c, "citation_id", "")).strip()
    }
    for e in events:
        eid = str(getattr(e, "event_id", "") or "").strip()
        if not eid:
            continue
        et = str(getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", "")) or "").lower()
        blobs = [str(t or "") for t in _event_text_blobs(e)]
        for cid in (getattr(e, "citation_ids", []) or []):
            c = citation_by_id.get(str(cid).strip())
            if c:
                blobs.append(str(getattr(c, "snippet", "") or ""))
        blob = " ".join(blobs).lower()
        event_cids = [str(c).strip() for c in (getattr(e, "citation_ids", []) or []) if str(c).strip()]

        is_ed = is_ed_event(
            text_blob=blob,
            event_type=et,
            provider_blob="",
            event_class=("ed_visit" if et in {"er_visit", "hospital_admission", "hospital_discharge"} else ""),
        )
        if is_ed:
            b = buckets["ed"]
            b.detected = True
            if eid not in b.event_ids:
                b.event_ids.append(eid)
            for cid in event_cids[:6]:
                if cid not in b.citation_ids:
                    b.citation_ids.append(cid)

        pt_context = ("pt_visit" in et) or bool(re.search(r"\b(physical therapy|pt)\b", blob))
        is_pt_eval = pt_context and bool(re.search(r"\b(initial evaluation|pt evaluation|plan of care)\b", blob))
        if is_pt_eval:
            b = buckets["pt_eval"]
            b.detected = True
            if eid not in b.event_ids:
                b.event_ids.append(eid)
            for cid in event_cids[:6]:
                if cid not in b.citation_ids:
                    b.citation_ids.append(cid)

    return buckets


def _dedupe_citation_ids(items: list[str] | None, limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        cid = str(item or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
        if len(out) >= limit:
            break
    return out


def _event_type_value(event: Event) -> str:
    return str(getattr(getattr(event, "event_type", None), "value", getattr(event, "event_type", "")) or "").lower()


def _encounter_class_label(event: Event, bucket_evidence: dict[str, BucketEvidence] | None = None) -> str:
    et = _event_type_value(event)
    if et == "er_visit":
        return "Emergency Department"
    if et == "hospital_admission":
        return "Hospital Admission"
    if et == "hospital_discharge":
        if (bucket_evidence or {}).get("ed", BucketEvidence()).detected:
            return "Emergency Department / Hospital Discharge"
        return "Hospital Discharge"
    if et == "inpatient_daily_note":
        return "Inpatient Hospital Care"
    if et == "office_visit":
        return "Office Visit"
    if et == "pt_visit":
        return "Physical Therapy"
    if et == "imaging_study":
        return "Imaging Study"
    if et == "procedure":
        return "Procedure"
    if et == "lab_result":
        return "Laboratory Testing"
    return et.replace("_", " ").title() or "Clinical Encounter"


def _care_phase_label(event: Event, bucket_evidence: dict[str, BucketEvidence] | None = None) -> str | None:
    et = _event_type_value(event)
    ed_detected = bool((bucket_evidence or {}).get("ed", BucketEvidence()).detected)
    if et in {"er_visit", "hospital_admission"}:
        return "Emergency department evaluation" if ed_detected else "Hospital admission"
    if et in {"hospital_discharge", "discharge"}:
        return "Discharge instructions"
    if et == "inpatient_daily_note":
        return "Inpatient monitoring"
    if et == "imaging_study":
        return "Diagnostic testing"
    if et == "lab_result":
        return "Laboratory testing"
    if et == "procedure":
        return "Procedure"
    if et == "pt_visit":
        return "Physical therapy"
    if et == "office_visit":
        return "Follow-up care"
    return None


def _build_case_skeleton(
    events: list[Event],
    citations: list[Citation] | None,
    *,
    promoted: list[PromotedFinding],
    top_case_drivers: list[str],
    bucket_evidence: dict[str, BucketEvidence],
    mechanism: RendererCitationValue,
) -> RendererCaseSkeleton:
    if top_case_drivers:
        return RendererCaseSkeleton()

    dated_events = [(start, event) for event in events if (start := _iso_from_event(event)[0])]
    dated_events.sort(key=lambda item: item[0])
    items: list[RendererCaseSkeletonItem] = []
    care_phases: list[RendererCaseSkeletonItem] = []

    unique_pages = sorted({
        int(getattr(c, "page_number", 0) or 0)
        for c in (citations or [])
        if int(getattr(c, "page_number", 0) or 0) > 0
    })
    unique_citation_ids = _dedupe_citation_ids([str(getattr(c, "citation_id", "") or "") for c in (citations or [])], limit=8)
    provider_ids = sorted({
        str(getattr(e, "provider_id", "") or "").strip()
        for e in events
        if str(getattr(e, "provider_id", "") or "").strip()
    })

    if dated_events:
        start_date, first_event = dated_events[0]
        items.append(
            RendererCaseSkeletonItem(
                label="Earliest encounter",
                value=start_date,
                citation_ids=_dedupe_citation_ids(list(getattr(first_event, "citation_ids", []) or [])),
            )
        )
        items.append(
            RendererCaseSkeletonItem(
                label="Encounter type",
                value=_encounter_class_label(first_event, bucket_evidence),
                citation_ids=_dedupe_citation_ids(list(getattr(first_event, "citation_ids", []) or [])),
            )
        )

    discharge_events = [e for e in events if _event_type_value(e) in {"hospital_discharge", "discharge"}]
    if discharge_events:
        discharge_event = sorted(discharge_events, key=lambda e: _iso_from_event(e)[0] or "9999-99-99")[0]
        discharge_date = _iso_from_event(discharge_event)[0]
        first_date = dated_events[0][0] if dated_events else None
        disposition = "Discharged same day" if first_date and discharge_date == first_date else "Discharged after inpatient stay"
        items.append(
            RendererCaseSkeletonItem(
                label="Disposition",
                value=disposition,
                citation_ids=_dedupe_citation_ids(list(getattr(discharge_event, "citation_ids", []) or [])),
            )
        )

    if provider_ids:
        items.append(
            RendererCaseSkeletonItem(
                label="Providers documented",
                value=f"{len(provider_ids)} documented",
                citation_ids=_dedupe_citation_ids([
                    cid for e in events for cid in list(getattr(e, "citation_ids", []) or [])
                ]),
            )
        )

    if unique_pages:
        items.append(
            RendererCaseSkeletonItem(
                label="Pages analyzed",
                value=str(len(unique_pages)),
                citation_ids=unique_citation_ids,
            )
        )

    if mechanism.value and mechanism.citation_ids:
        items.append(
            RendererCaseSkeletonItem(
                label="Mechanism documented",
                value="Yes",
                citation_ids=_dedupe_citation_ids(list(mechanism.citation_ids or [])),
            )
        )

    seen_phase_labels: set[str] = set()
    for _event_date, event in dated_events:
        label = _care_phase_label(event, bucket_evidence)
        if not label or label in seen_phase_labels:
            continue
        seen_phase_labels.add(label)
        care_phases.append(
            RendererCaseSkeletonItem(
                label="Care phase",
                value=label,
                citation_ids=_dedupe_citation_ids(list(getattr(event, "citation_ids", []) or [])),
            )
        )
        if len(care_phases) >= 4:
            break

    if not items and not care_phases:
        return RendererCaseSkeleton()
    return RendererCaseSkeleton(active=True, items=items, care_phases=care_phases)


def _billing_completeness(specials_summary: dict | None) -> str:
    if not isinstance(specials_summary, dict):
        return "none"
    flags = {str(f) for f in (specials_summary.get("flags") or [])}
    if "NO_BILLING_DATA" in flags:
        return "none"
    if {"PARTIAL_BILLING_ONLY", "MISSING_EOB_DATA"} & flags:
        return "partial"
    if specials_summary.get("by_provider") or (specials_summary.get("totals") or {}).get("total_charges"):
        return "complete"
    return "none"


def _alignment_claim_type_for_category(category: str) -> str | None:
    return {
        "diagnosis": "diagnosis",
        "imaging": "imaging_finding",
        "procedure": "procedure",
        "visit_count": "pt_claim",
    }.get(str(category or "").strip().lower())


def _alignment_claim_id(claim_type: str, claim_text: str, hint: str) -> str:
    base = f"{claim_type}|{claim_text}|{hint}".encode("utf-8", "ignore")
    return hashlib.sha1(base).hexdigest()[:12]


def _norm_alignment_text(value: Any) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _norm_alignment_citations(value: Any) -> tuple[str, ...]:
    out: list[str] = []
    for c in (value or []):
        sc = str(c or "").strip().lower()
        if not sc:
            continue
        sc = re.sub(r"^p\.\s*", "", sc)
        out.append(sc)
    return tuple(sorted(set(out)))


def _claim_alignment_lookup(claim_alignment: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str, tuple[str, ...]], dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_norm: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    if not isinstance(claim_alignment, dict):
        return by_id, by_norm
    for row in (claim_alignment.get("claims") or []):
        if not isinstance(row, dict):
            continue
        cid = str(row.get("claim_id") or "").strip()
        if cid:
            by_id[cid] = row
        key = (
            str(row.get("claim_type") or "").strip().lower(),
            _norm_alignment_text(row.get("claim_text")),
            _norm_alignment_citations(row.get("citations")),
        )
        if key[0] and key[1] and key not in by_norm:
            by_norm[key] = row
    return by_id, by_norm


def annotate_renderer_manifest_claim_context_alignment(
    renderer_manifest: RendererManifest | dict | None,
    evidence_graph_extensions: dict[str, Any] | None,
) -> RendererManifest | dict | None:
    if isinstance(renderer_manifest, RendererManifest):
        base = renderer_manifest
        as_dict = base.model_dump(mode="json")
    elif isinstance(renderer_manifest, dict):
        base = None
        as_dict = dict(renderer_manifest)
    else:
        return renderer_manifest

    ext = evidence_graph_extensions if isinstance(evidence_graph_extensions, dict) else {}
    claim_alignment = ext.get("claim_context_alignment")
    if not isinstance(claim_alignment, dict):
        return renderer_manifest

    promoted = [pf for pf in (as_dict.get("promoted_findings") or []) if isinstance(pf, dict)]
    if not promoted:
        return renderer_manifest

    claims_by_id, claims_by_norm = _claim_alignment_lookup(claim_alignment)
    annotated: list[dict[str, Any]] = []
    for idx, pf in enumerate(promoted):
        item = dict(pf)
        category = str(item.get("category") or "").strip().lower()
        claim_type = _alignment_claim_type_for_category(category)
        claim_row: dict[str, Any] | None = None
        if claim_type:
            claim_text = str(item.get("label") or "").strip()
            stable_id = _alignment_claim_id(claim_type, claim_text, f"{category}:{idx}")
            claim_row = claims_by_id.get(stable_id)
            if claim_row is None:
                key = (
                    claim_type,
                    _norm_alignment_text(claim_text),
                    _norm_alignment_citations(item.get("citation_ids")),
                )
                claim_row = claims_by_norm.get(key)
            if claim_row is not None:
                item["alignment_status"] = str(claim_row.get("severity") or "PASS").upper() or "PASS"
                item["alignment_reason"] = str(claim_row.get("reason_code") or "").strip() or None
                item["alignment_claim_id"] = str(claim_row.get("claim_id") or stable_id).strip() or stable_id
                # INV-Q5 (Pass 045): Unverified context must never reach snapshot bullets.
                # If alignment_status is not PASS, force headline_eligible=False so the item
                # can only appear in Additional Findings (INTERNAL mode only), never in the
                # main settlement driver rows or density backfill.
                al_st = str(item.get("alignment_status") or "").strip().upper()
                if al_st not in {"", "PASS"}:
                    item["headline_eligible"] = False
        annotated.append(item)

    as_dict["promoted_findings"] = annotated
    if base is None:
        return as_dict
    return RendererManifest.model_validate(as_dict)


def build_renderer_manifest(
    *,
    events: list[Event],
    evidence_graph_extensions: dict[str, Any] | None,
    specials_summary: dict | None,
    citations: list[Citation] | None = None,
) -> RendererManifest:
    ext = evidence_graph_extensions if isinstance(evidence_graph_extensions, dict) else {}
    claim_rows = list(ext.get("claim_rows") or [])
    promoted = _promoted_findings_from_claim_rows(claim_rows)
    promoted = _promoted_findings_from_events(events, promoted)
    promoted = _promoted_findings_from_citations(citations, promoted)
    promoted = _consolidate_promoted_findings(promoted)
    promoted = _normalize_promoted_citation_ids_with_hard_gate(promoted, citations)
    mechanism_from_citations, mechanism_citation_audit = _build_mechanism_from_citations_with_audit(citations)
    mechanism, mechanism_audit = _build_mechanism_from_events(events, citations)
    if not mechanism.value:
        mechanism = mechanism_from_citations
        if mechanism_citation_audit.get("selected_label"):
            mechanism_audit = {
                **(mechanism_audit or {}),
                "fallback_selected_label": mechanism_citation_audit.get("selected_label"),
                "fallback_selected_citation_ids": mechanism_citation_audit.get("selected_citation_ids"),
                "fallback_selected_candidate": mechanism_citation_audit.get("selected_candidate"),
                "fallback_candidate_count": mechanism_citation_audit.get("candidate_count"),
                "fallback_top_candidates": mechanism_citation_audit.get("top_candidates", [])[:10],
            }
    top_case_drivers = _top_case_drivers_from_claim_rows(claim_rows)
    if len(top_case_drivers) < 3:
        top_case_drivers = _top_case_driver_fallback_from_events(events, top_case_drivers)
    bucket_evidence = _build_bucket_evidence(events, citations)
    case_skeleton = _build_case_skeleton(
        events,
        citations,
        promoted=promoted,
        top_case_drivers=top_case_drivers,
        bucket_evidence=bucket_evidence,
        mechanism=mechanism,
    )
    manifest = RendererManifest(
        doi=_build_doi(events),
        mechanism=mechanism,
        pt_summary=_build_pt_summary(events, citations, ext),
        promoted_findings=promoted,
        top_case_drivers=top_case_drivers,
        bucket_evidence=bucket_evidence,
        case_skeleton=case_skeleton,
        billing_completeness=_billing_completeness(specials_summary),
    )
    if isinstance(ext, dict):
        ext["mechanism_selection_audit"] = mechanism_audit
    annotated = annotate_renderer_manifest_claim_context_alignment(manifest, ext)
    return annotated if isinstance(annotated, RendererManifest) else manifest
