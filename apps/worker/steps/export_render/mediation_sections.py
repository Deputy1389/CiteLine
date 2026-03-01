"""
Mediation Leverage Sections — Pass31 + Pass32

Deterministic section generator for MEDIATION export mode.
Each section exposes:
  - title: str
  - items: list[MediationItem]  (label + citation support text)
  - gate_required: bool  (conditional completeness gate)

Section order is enforced by build_mediation_sections():
  1. Medical Severity Profile
  2. Mechanism & Initial Presentation  [+ time compression signal]
  3. Objective Findings                [imaging-first, pain-score filtered]
  4. Provider Corroboration            [Pass32 — optional, entity-ID gated]
  5. Treatment Progression             [+ milestone dates]
  6. Functional Limitations            [disability-first ordering]
  7. Current Condition & Prognosis     [Pass32 — last-window rule]
  8. Clinical Course & Reasonableness  [Pass32 — escalation-gated]
  9. Economic Damages Summary
 10. Anticipated Defense Arguments & Context
 11. (Chronology is page 3 — rendered by timeline_pdf.py, not this module)

Rules:
- No LLM calls.
- No chronology mutation.
- No scoring/model changes.
- Deterministic only.
- Renderer-formats-only: all clinical inference is done upstream in the pipeline.
- Fail only on present-but-not-surfaced signals (not absent-in-record conditions).
- Under-trigger is always safer than over-trigger.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class MediationItem:
    """A single line item inside a mediation section."""
    label: str
    support: str = ""   # pre-formatted citation text, e.g. "[p. 5] [p. 12]"


@dataclass
class MediationSection:
    """One titled section in the mediation leverage brief."""
    key: str
    title: str
    items: list[MediationItem] = field(default_factory=list)
    gate_required: bool = False   # True if this section is required given the evidence
    gate_fail: bool = False       # True if required but absent


# ---------------------------------------------------------------------------
# Shared helpers (no medical inference — reads pipeline-produced structured data)
# ---------------------------------------------------------------------------

def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()[:500]


def _is_sentinel(date_str: str | None) -> bool:
    s = str(date_str or "").strip()
    return not s or s in {"1900-01-01", "9999-12-31", "undated", "unknown"} or s.startswith("1900")


def _parse_date(val: Any) -> datetime.date | None:
    """Normalize any date-like value to datetime.date, or None.
    Returns None for sentinel years (<=1900) and far-future years (>=9000).
    """
    if val is None:
        return None
    # Already has date components (date or datetime)
    if hasattr(val, "year") and hasattr(val, "month") and hasattr(val, "day"):
        if hasattr(val, "date"):
            try:
                d = val.date()
            except TypeError:
                d = val  # type: ignore[assignment]
        else:
            d = val  # type: ignore[assignment]
        if d.year <= 1900 or d.year >= 9000:
            return None
        return d
    # String — check for sentinel strings before parsing
    s = str(val)[:10]
    if _is_sentinel(s):
        return None
    try:
        d = datetime.date.fromisoformat(s)
        if d.year <= 1900 or d.year >= 9000:
            return None
        return d
    except Exception:
        return None


def _cids_to_citation_text(cids: list[str], citation_by_id: dict[str, Any] | None) -> str:
    """Convert citation IDs to '[p. N]' format using citation_by_id map."""
    if not cids or not citation_by_id:
        return ""
    pages: list[int] = []
    seen: set[int] = set()
    for cid in cids:
        row = citation_by_id.get(str(cid))
        if not row:
            continue
        page_no = int(row.get("local_page") or row.get("global_page") or 0)
        if page_no > 0 and page_no not in seen:
            seen.add(page_no)
            pages.append(page_no)
    if not pages:
        return ""
    return " ".join(f"[p. {p}]" for p in sorted(pages)[:6])


def _refs_to_citation_text(refs: list[dict[str, Any]]) -> str:
    """Convert event citation refs list to '[p. N]' format."""
    pages: list[int] = []
    seen: set[int] = set()
    for ref in refs:
        page_no = int(ref.get("local_page") or ref.get("global_page") or 0)
        if page_no > 0 and page_no not in seen:
            seen.add(page_no)
            pages.append(page_no)
    if not pages:
        return ""
    return " ".join(f"[p. {p}]" for p in sorted(pages)[:6])


def _pages_to_citation_text(raw_citations: list[str]) -> str:
    """Extract page numbers from strings like 'p. 12' and format them."""
    pages: list[int] = []
    seen: set[int] = set()
    for raw in raw_citations:
        m = re.search(r"\bp\.\s*(\d+)\b", str(raw or ""), re.I)
        if m:
            p = int(m.group(1))
            if p > 0 and p not in seen:
                seen.add(p)
                pages.append(p)
    if not pages:
        return ""
    return " ".join(f"[p. {p}]" for p in sorted(pages)[:6])


def _event_first_date(event: Any) -> Any:
    """Return the first date value for an event, or None."""
    d = getattr(event, "date", None)
    if not d:
        return None
    val = getattr(d, "value", d)
    if hasattr(val, "start"):
        return val.start
    if hasattr(val, "isoformat"):
        return val
    return None


def _first_fact_text(event: Any) -> str:
    """Return the first clean, non-meta fact text from an event."""
    pools = [
        getattr(event, "exam_findings", []) or [],
        getattr(event, "diagnoses", []) or [],
        getattr(event, "facts", []) or [],
    ]
    for pool in pools:
        for fact in pool:
            txt = _clean(getattr(fact, "text", "") or "")
            if txt and len(txt.split()) >= 3:
                return txt
    return ""


def _sorted_dated_events(raw_events: list) -> list[tuple[Any, datetime.date]]:
    """Return (event, date) pairs sorted ascending by date, skipping undated events."""
    pairs = []
    for e in raw_events:
        raw_d = _event_first_date(e)
        d = _parse_date(raw_d)
        if d is not None:
            pairs.append((e, d))
    pairs.sort(key=lambda x: x[1])
    return pairs


# ---------------------------------------------------------------------------
# Pass32 pattern constants (pipeline-produced label matching — not free text)
# ---------------------------------------------------------------------------

# Pain-score lines to exclude from objective findings
_PAIN_SCORE_PATTERN = re.compile(r"\bpain\b.{0,25}\d+\s*/\s*10", re.I)

# Referral / continued-care signal (checked against promoted_findings labels)
_REFERRAL_PATTERN = re.compile(
    r"\b(referral|follow.up|continued care|return to care|ongoing care|further evaluation|follow up)\b",
    re.I,
)

# Surgical candidacy signal (checked against promoted_findings labels)
_SURGICAL_CANDIDACY_PATTERN = re.compile(
    r"\b(surgical candidate|surgery candidate|candidate for surgery|surgical intervention|operative candidate)\b",
    re.I,
)

# Objective condition keywords used for provider corroboration grouping
_CORROBORATION_CONDITION_PATTERN = re.compile(
    r"\b(disc|radiculopathy|stenosis|herniation|fracture|compression|displacement)\b",
    re.I,
)

# Functional sub-priorities for reordering within functional limitations section
_DISABILITY_PRIORITY_PATTERN = re.compile(
    r"\b(disability|impairment|MMI|maximum medical improvement|rating)\b",
    re.I,
)
_WORK_RESTRICTION_PRIORITY_PATTERN = re.compile(
    r"\b(work restriction|work-related|lifting limit|restricted from|unable to|inability to)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Section 1: Medical Severity Profile
# ---------------------------------------------------------------------------

def _build_severity_profile_section(ext: dict, rm: dict) -> MediationSection:
    """
    Build from severity_profile extension (pipeline-populated).
    Required if severity_profile is present in ext.
    """
    sp = ext.get("severity_profile") if isinstance(ext.get("severity_profile"), dict) else {}
    items: list[MediationItem] = []

    if sp:
        primary = _clean(sp.get("primary_label"))
        if primary:
            items.append(MediationItem(label=primary))

        for row in (sp.get("severity_drivers") or [])[:4]:
            if not isinstance(row, dict):
                continue
            label = _clean(row.get("label"))
            if label:
                items.append(MediationItem(label=label))

        for row in (sp.get("treatment_progression") or [])[:2]:
            if not isinstance(row, dict):
                continue
            label = _clean(row.get("label"))
            if label:
                items.append(MediationItem(label=label))

        # Citations from support block
        support = sp.get("support") if isinstance(sp.get("support"), dict) else {}
        page_refs = [r for r in (support.get("page_refs") or []) if isinstance(r, dict)]
        page_nums = sorted({int(r.get("page_number") or 0) for r in page_refs if int(r.get("page_number") or 0) > 0})
        cite_str = " ".join(f"[p. {p}]" for p in page_nums[:8]) if page_nums else ""
        if items and cite_str:
            items[-1] = MediationItem(label=items[-1].label, support=cite_str)

    gate_required = bool(sp)
    return MediationSection(
        key="severity_profile",
        title="MEDICAL SEVERITY PROFILE",
        items=items,
        gate_required=gate_required,
        gate_fail=gate_required and not bool(items),
    )


# ---------------------------------------------------------------------------
# Section 2: Mechanism & Initial Presentation  [Pass32: 3-part + time compression]
# ---------------------------------------------------------------------------

def _build_mechanism_section(
    ext: dict,
    rm: dict,
    raw_events: list | None = None,
    event_citations_by_event: dict | None = None,
    citation_by_id: dict | None = None,
) -> MediationSection:
    """
    Three-part deterministic format:
      1. Mechanism (from renderer_manifest)
      2. Initial complaint/presentation (earliest dated event first fact)
      3. Initial diagnosis/objective line (earliest event diagnoses)
    Plus Pass32 time compression signal:
      - "Treatment initiated within N days of documented injury."
      - "Documented care span: N months." (if span >= 30 days)
    Required if any encounter exists.
    """
    items: list[MediationItem] = []

    # ── Part 1a: Date of Injury ──────────────────────────────────────────────
    rm_doi = rm.get("doi") or {} if isinstance(rm, dict) else {}
    doi_date: datetime.date | None = None
    doi_val = ""
    if isinstance(rm_doi, dict):
        doi_val = _clean(rm_doi.get("value"))
        if doi_val and not _is_sentinel(doi_val):
            doi_date = _parse_date(doi_val)
            doi_cids = [str(c) for c in (rm_doi.get("citation_ids") or [])]
            doi_cite = _cids_to_citation_text(doi_cids, citation_by_id)
            items.append(MediationItem(label=f"Date of Injury: {doi_val}", support=doi_cite))

    # ── Part 1b: Mechanism ───────────────────────────────────────────────────
    rm_mech = rm.get("mechanism") or {} if isinstance(rm, dict) else {}
    if isinstance(rm_mech, dict):
        mech_val = _clean(rm_mech.get("value"))
        if mech_val:
            mech_cids = [str(c) for c in (rm_mech.get("citation_ids") or [])]
            mech_cite = _cids_to_citation_text(mech_cids, citation_by_id)
            items.append(MediationItem(label=f"Mechanism: {mech_val}", support=mech_cite))

    # ── Part 2: Initial presentation (earliest dated event) ─────────────────
    dated_pairs: list[tuple[Any, datetime.date]] = []
    if raw_events:
        dated_pairs = _sorted_dated_events(raw_events)

    if dated_pairs:
        earliest_evt, earliest_date = dated_pairs[0]
        initial_fact = _first_fact_text(earliest_evt)
        if initial_fact:
            refs = (event_citations_by_event or {}).get(str(getattr(earliest_evt, "event_id", "")), [])
            init_cite = _refs_to_citation_text(refs)
            items.append(MediationItem(label=f"Initial presentation: {initial_fact}", support=init_cite))

        # ── Part 3: Initial diagnosis line ──────────────────────────────────
        diagnoses = getattr(earliest_evt, "diagnoses", None) or []
        for dx in diagnoses:
            dx_text = _clean(getattr(dx, "text", "") or "")
            if dx_text and len(dx_text.split()) >= 2:
                refs = (event_citations_by_event or {}).get(str(getattr(earliest_evt, "event_id", "")), [])
                dx_cite = _refs_to_citation_text(refs)
                items.append(MediationItem(label=f"Initial diagnosis: {dx_text}", support=dx_cite))
                break  # only the first distinct diagnosis

    # ── Pass32: Time Compression Signal ─────────────────────────────────────
    if dated_pairs and doi_date is not None:
        first_treat_date = dated_pairs[0][1]
        last_treat_date = dated_pairs[-1][1]

        # Days from DOI to first treatment
        try:
            days_to_first = (first_treat_date - doi_date).days
            if 0 <= days_to_first <= 365:
                plural = "s" if days_to_first != 1 else ""
                first_evt_refs = (event_citations_by_event or {}).get(
                    str(getattr(dated_pairs[0][0], "event_id", "")), []
                )
                first_cite = _refs_to_citation_text(first_evt_refs)
                items.append(MediationItem(
                    label=f"Treatment initiated within {days_to_first} day{plural} of documented injury.",
                    support=first_cite,
                ))
        except Exception:
            pass

        # Treatment span
        try:
            span_days = (last_treat_date - first_treat_date).days
            if span_days >= 30:
                span_months = round(span_days / 30.44)
                if span_months >= 1:
                    plural = "s" if span_months != 1 else ""
                    items.append(MediationItem(
                        label=f"Documented care span: {span_months} month{plural}.",
                    ))
        except Exception:
            pass

    gate_required = bool(raw_events)
    return MediationSection(
        key="mechanism_initial_presentation",
        title="MECHANISM & INITIAL PRESENTATION",
        items=items,
        gate_required=gate_required,
        gate_fail=gate_required and not bool(items),
    )


# ---------------------------------------------------------------------------
# Section 3: Objective Findings  [Pass32: imaging-first ordering, pain-score filter]
# ---------------------------------------------------------------------------

# Categories "objective_deficit" and "imaging" are the primary structural trigger.
_OBJECTIVE_TRIGGER_CATEGORIES = frozenset({"objective_deficit", "imaging"})
_OBJECTIVE_TRIGGER_KEYS = re.compile(
    r"\b(disc|protrusion|herniation|radiculopathy|stenosis|tear|fracture|"
    r"mri|ct scan|x-ray|xray|deficit|restriction|compression|displacement)\b",
    re.I,
)


def _objective_trigger(ext: dict, rm: dict) -> bool:
    """True if objective/imaging evidence is present in manifest or bucket evidence."""
    if isinstance(rm, dict):
        for finding in (rm.get("promoted_findings") or []):
            if not isinstance(finding, dict):
                continue
            if str(finding.get("category") or "").lower() in _OBJECTIVE_TRIGGER_CATEGORIES:
                return True
            if _OBJECTIVE_TRIGGER_KEYS.search(str(finding.get("label") or "")):
                return True
        # Check bucket evidence
        bucket_ev = rm.get("bucket_evidence") if isinstance(rm.get("bucket_evidence"), dict) else {}
        if isinstance(bucket_ev, dict):
            for bucket_val in bucket_ev.values():
                if isinstance(bucket_val, dict) and bucket_val.get("detected"):
                    return True
    return False


def _build_objective_findings_section(
    ext: dict,
    rm: dict,
    citation_by_id: dict | None = None,
) -> MediationSection:
    """
    Surface objective findings when trigger is true.
    Excludes subjective-only symptom rows (category == "symptom").
    Excludes pain-score-only lines (e.g. "pain 8/10").
    Imaging findings ordered before objective_deficit findings.
    Required only if trigger is true.
    """
    trigger = _objective_trigger(ext, rm)
    imaging_items: list[MediationItem] = []
    deficit_items: list[MediationItem] = []

    if trigger and isinstance(rm, dict):
        seen_labels: set[str] = set()
        for finding in (rm.get("promoted_findings") or []):
            if not isinstance(finding, dict):
                continue
            category = str(finding.get("category") or "").lower()
            if category == "symptom":
                continue
            if category not in _OBJECTIVE_TRIGGER_CATEGORIES:
                continue
            label = _clean(finding.get("label"))
            if not label or label.lower() in seen_labels:
                continue
            # Exclude pain-score-only lines
            if _PAIN_SCORE_PATTERN.search(label):
                continue
            seen_labels.add(label.lower())
            cids = [str(c) for c in (finding.get("citation_ids") or [])]
            support = _cids_to_citation_text(cids, citation_by_id)
            item = MediationItem(label=label, support=support)
            if category == "imaging":
                imaging_items.append(item)
            else:
                deficit_items.append(item)

    # Imaging first, then objective deficits; cap at 8 total
    items = (imaging_items + deficit_items)[:8]

    return MediationSection(
        key="objective_findings",
        title="OBJECTIVE FINDINGS",
        items=items,
        gate_required=trigger,
        gate_fail=trigger and not bool(items),
    )


# ---------------------------------------------------------------------------
# Section 4: Treatment Escalation Ladder  [Pass32: earliest milestone dates]
# ---------------------------------------------------------------------------

_CANONICAL_STAGE_ORDER = ["ed", "imaging", "pt", "specialist", "procedure", "surgery"]

_STAGE_LABELS = {
    "ed": "Emergency Department",
    "imaging": "Diagnostic Imaging",
    "pt": "Physical Therapy / Rehabilitation",
    "specialist": "Specialist Consultation",
    "procedure": "Procedure / Injection",
    "surgery": "Surgery",
}

_STAGE_EVENT_TYPES: dict[str, frozenset[str]] = {
    "ed": frozenset({"er_visit", "hospital_admission", "hospital_discharge", "inpatient_daily_note"}),
    "imaging": frozenset({"mri", "xray", "ct_scan", "imaging", "radiology", "imaging_study"}),
    "pt": frozenset({"pt_visit", "pt_eval", "chiropractic", "physical_therapy", "rehab"}),
    "specialist": frozenset({"specialist_visit", "orthopedic_visit", "neurology_visit", "pain_management_visit", "specialist"}),
    "procedure": frozenset({"injection", "procedure", "nerve_block", "epidural_steroid", "epidural", "cortisone"}),
    "surgery": frozenset({"surgery", "surgical_procedure", "operation"}),
}


def _detect_stages(
    raw_events: list | None,
    rm: dict,
) -> list[str]:
    """
    Detect which canonical stages are evidenced.
    Returns stages in canonical order.
    """
    present: set[str] = set()

    if raw_events:
        for evt in raw_events:
            evtype = str(
                getattr(getattr(evt, "event_type", None), "value", getattr(evt, "event_type", "")) or ""
            ).lower().strip()
            for stage, types in _STAGE_EVENT_TYPES.items():
                if evtype in types:
                    present.add(stage)

    # Also check bucket_evidence from manifest
    bucket_ev = rm.get("bucket_evidence") if isinstance(rm, dict) and isinstance(rm.get("bucket_evidence"), dict) else {}
    if isinstance(bucket_ev, dict):
        if isinstance(bucket_ev.get("ed"), dict) and bucket_ev["ed"].get("detected"):
            present.add("ed")
        if isinstance(bucket_ev.get("pt_eval"), dict) and bucket_ev["pt_eval"].get("detected"):
            present.add("pt")

    return [s for s in _CANONICAL_STAGE_ORDER if s in present]


def _build_treatment_progression_section(
    ext: dict,
    rm: dict,
    raw_events: list | None = None,
    event_citations_by_event: dict | None = None,
    citation_by_id: dict | None = None,
) -> MediationSection:
    """
    Build from detected stages in canonical order.
    Adds earliest milestone date to each stage label when available.
    Required if >1 stage exists.
    Always canonical order — never unsorted.
    """
    stages = _detect_stages(raw_events, rm)

    # Build earliest-date map per stage
    stage_earliest: dict[str, tuple[Any, datetime.date]] = {}  # stage -> (event, date)
    if raw_events:
        for evt in raw_events:
            evtype = str(
                getattr(getattr(evt, "event_type", None), "value", getattr(evt, "event_type", "")) or ""
            ).lower().strip()
            raw_d = _event_first_date(evt)
            d = _parse_date(raw_d)
            if d is None:
                continue
            for stage, types in _STAGE_EVENT_TYPES.items():
                if evtype in types:
                    existing = stage_earliest.get(stage)
                    if existing is None or d < existing[1]:
                        stage_earliest[stage] = (evt, d)

    items: list[MediationItem] = []
    for stage in stages:
        base_label = _STAGE_LABELS.get(stage, stage.replace("_", " ").title())

        # Append earliest date if available
        earliest_entry = stage_earliest.get(stage)
        if earliest_entry is not None:
            _, earliest_date = earliest_entry
            label = f"{base_label} – {earliest_date.isoformat()}"
        else:
            label = base_label

        # Citation from earliest event in this stage
        support = ""
        if earliest_entry is not None and event_citations_by_event:
            earliest_evt, _ = earliest_entry
            refs = event_citations_by_event.get(str(getattr(earliest_evt, "event_id", "")), [])
            if refs:
                support = _refs_to_citation_text(refs[:3])
        elif raw_events and event_citations_by_event:
            # Fallback: first event of this type
            types = _STAGE_EVENT_TYPES.get(stage, frozenset())
            for evt in raw_events:
                evtype = str(
                    getattr(getattr(evt, "event_type", None), "value", getattr(evt, "event_type", "")) or ""
                ).lower().strip()
                if evtype in types:
                    refs = event_citations_by_event.get(str(getattr(evt, "event_id", "")), [])
                    if refs:
                        support = _refs_to_citation_text(refs[:3])
                        break

        items.append(MediationItem(label=label, support=support))

    gate_required = len(stages) > 1
    return MediationSection(
        key="treatment_progression",
        title="TREATMENT PROGRESSION",
        items=items,
        gate_required=gate_required,
        gate_fail=gate_required and not bool(items),
    )


# ---------------------------------------------------------------------------
# Section 5: Functional Limitations  [Pass32: disability-first ordering]
# ---------------------------------------------------------------------------

_FUNCTIONAL_PATTERN = re.compile(
    r"\b(disability|work restriction|work-related|lifting limit|activity limit|"
    r"permanent|impairment|MMI|maximum medical improvement|functional limit|"
    r"limited to|inability to|unable to|restricted from)\b",
    re.I,
)


def _func_sort_priority(label: str) -> int:
    """0 = disability/rating, 1 = work restriction, 2 = generic."""
    if _DISABILITY_PRIORITY_PATTERN.search(label):
        return 0
    if _WORK_RESTRICTION_PRIORITY_PATTERN.search(label):
        return 1
    return 2


def _functional_trigger(ext: dict, rm: dict) -> bool:
    """True if functional limitation signals are present in manifest or claim_rows."""
    if isinstance(rm, dict):
        for finding in (rm.get("promoted_findings") or []):
            if not isinstance(finding, dict):
                continue
            if _FUNCTIONAL_PATTERN.search(str(finding.get("label") or "")):
                return True
    for row in (ext.get("claim_rows") or []):
        if not isinstance(row, dict):
            continue
        if _FUNCTIONAL_PATTERN.search(str(row.get("assertion") or "")):
            return True
    return False


def _build_functional_limitations_section(
    ext: dict,
    rm: dict,
    citation_by_id: dict | None = None,
) -> MediationSection:
    """
    Surface functional limitations when trigger is true.
    Items ordered: disability ratings first, work restrictions second, generic last.
    Required only if functional trigger is true.
    """
    trigger = _functional_trigger(ext, rm)
    raw_items: list[MediationItem] = []

    if trigger:
        seen: set[str] = set()
        if isinstance(rm, dict):
            for finding in (rm.get("promoted_findings") or []):
                if not isinstance(finding, dict):
                    continue
                label = _clean(finding.get("label"))
                if not label or not _FUNCTIONAL_PATTERN.search(label):
                    continue
                if label.lower() in seen:
                    continue
                seen.add(label.lower())
                cids = [str(c) for c in (finding.get("citation_ids") or [])]
                support = _cids_to_citation_text(cids, citation_by_id)
                raw_items.append(MediationItem(label=label, support=support))
                if len(raw_items) >= 6:
                    break

        if not raw_items:
            for row in (ext.get("claim_rows") or []):
                if not isinstance(row, dict):
                    continue
                text = _clean(str(row.get("assertion") or ""))
                if not text or not _FUNCTIONAL_PATTERN.search(text):
                    continue
                if text.lower() in seen:
                    continue
                seen.add(text.lower())
                raw_cits = [str(c) for c in (row.get("citations") or []) if str(c).strip()]
                support = _pages_to_citation_text(raw_cits)
                raw_items.append(MediationItem(label=text, support=support))
                if len(raw_items) >= 6:
                    break

    # Reorder: disability ratings first, work restrictions second, generic last
    items = sorted(raw_items, key=lambda it: _func_sort_priority(it.label))[:4]

    return MediationSection(
        key="functional_limitations",
        title="FUNCTIONAL LIMITATIONS",
        items=items,
        gate_required=trigger,
        gate_fail=trigger and not bool(items),
    )


# ---------------------------------------------------------------------------
# Section 6: Economic Damages Summary (Honesty Rule)
# ---------------------------------------------------------------------------

def _build_economic_damages_section(
    ext: dict,
    rm: dict,
    specials_summary: dict | None = None,
) -> MediationSection:
    """
    Print structured specials total when available; explicit non-inference line when absent.
    Never infers/sums raw invoices.
    Required only if structured specials total exists.
    """
    items: list[MediationItem] = []
    has_structured_total = False

    if isinstance(specials_summary, dict):
        totals = specials_summary.get("totals") or {}
        total_charges = totals.get("total_charges") if isinstance(totals, dict) else None
        if total_charges:
            try:
                val = float(total_charges)
                if val > 0:
                    has_structured_total = True
                    items.append(MediationItem(label=f"Total medical specials: ${val:,.2f}"))
                    for prov in (specials_summary.get("by_provider") or [])[:4]:
                        if not isinstance(prov, dict):
                            continue
                        pname = _clean(prov.get("provider") or prov.get("provider_name"))
                        pamount = prov.get("total_charges") or prov.get("amount")
                        if pname and pamount:
                            try:
                                items.append(MediationItem(label=f"  • {pname}: ${float(pamount):,.2f}"))
                            except Exception:
                                pass
            except Exception:
                pass

    # Honesty disclosure when no structured total (phrasing avoids placeholder scanner false positive)
    if not has_structured_total:
        items.append(MediationItem(
            label="Billing specials: Structured totals were not captured in this extraction.",
        ))

    gate_required = has_structured_total
    return MediationSection(
        key="economic_damages",
        title="ECONOMIC DAMAGES SUMMARY",
        items=items,
        gate_required=gate_required,
        gate_fail=False,  # section always present (either total or disclosure)
    )


# ---------------------------------------------------------------------------
# Section 7: Defense Preemption Templates (Locked Text)
# ---------------------------------------------------------------------------

_DEFENSE_TEMPLATES: dict[str, str] = {
    "prior_injury": "Prior similar history is documented; context appears in records.",
    "care_gap": "A gap in care is documented; context appears in records.",
    "delayed_treatment": "Timing of first treatment is documented; context appears in records.",
}


def _detect_defense_flags(
    ext: dict,
    rm: dict,
    gaps: list | None = None,
) -> dict[str, bool]:
    """
    Detect active defense flags from structured pipeline data.
    Returns dict: {flag_key: bool}.
    """
    flags: dict[str, bool] = {k: False for k in _DEFENSE_TEMPLATES}

    lsv1 = ext.get("litigation_safe_v1") if isinstance(ext.get("litigation_safe_v1"), dict) else {}
    for claim in (lsv1.get("claims") or []):
        if not isinstance(claim, dict):
            continue
        ctype = str(claim.get("claim_type") or "").lower()
        if "prior" in ctype:
            flags["prior_injury"] = True
            break
    if not flags["prior_injury"]:
        for row in (ext.get("claim_rows") or []):
            if not isinstance(row, dict):
                continue
            ctype = str(row.get("claim_type") or "").lower()
            if "prior" in ctype:
                flags["prior_injury"] = True
                break

    if gaps:
        for g in gaps:
            try:
                duration = int(getattr(g, "duration_days", None) or 0)
                if duration > 45:
                    flags["care_gap"] = True
                    break
            except Exception:
                pass
    if not flags["care_gap"]:
        computed = lsv1.get("computed") if isinstance(lsv1.get("computed"), dict) else {}
        try:
            if int(computed.get("max_gap_days") or 0) > 45:
                flags["care_gap"] = True
        except Exception:
            pass

    computed = lsv1.get("computed") if isinstance(lsv1.get("computed"), dict) else {}
    try:
        days_to_first = computed.get("days_to_first_treatment")
        if days_to_first is not None and int(days_to_first) > 7:
            flags["delayed_treatment"] = True
    except Exception:
        pass

    return flags


def _build_defense_preemption_section(
    ext: dict,
    rm: dict,
    gaps: list | None = None,
) -> MediationSection:
    """
    Emit locked template text for each active defense flag.
    NO severity tags. NO penalties. NO valuation language.
    Required only if any defense flags are active.
    """
    flags = _detect_defense_flags(ext, rm, gaps)
    items: list[MediationItem] = []

    for flag_key, template_text in _DEFENSE_TEMPLATES.items():
        if flags.get(flag_key):
            items.append(MediationItem(label=template_text))

    gate_required = any(flags.values())
    return MediationSection(
        key="defense_preemption",
        title="ANTICIPATED DEFENSE ARGUMENTS & CONTEXT",
        items=items,
        gate_required=gate_required,
        gate_fail=gate_required and not bool(items),
    )


# ---------------------------------------------------------------------------
# Pass32 — Escalation helper
# ---------------------------------------------------------------------------

_CONSERVATIVE_STAGES = frozenset({"ed", "pt"})
_ADVANCED_STAGES = frozenset({"specialist", "procedure", "surgery"})


def _detect_escalation(stages: list[str]) -> bool:
    """
    True if treatment stages represent genuine escalation (not merely 2 stages).

    Escalation rules:
    1. Conservative stage (ed or pt) AND advanced stage (specialist/procedure/surgery) both present.
    2. Imaging stage AND at least one conservative stage present.

    ED + PT alone is NOT escalation.
    """
    stage_set = set(stages)
    # Rule 1: conservative care followed by higher-tier intervention
    if stage_set & _CONSERVATIVE_STAGES and stage_set & _ADVANCED_STAGES:
        return True
    # Rule 2: imaging ordered (implies persistence warranted further workup)
    if "imaging" in stage_set and stage_set & _CONSERVATIVE_STAGES:
        return True
    return False


# ---------------------------------------------------------------------------
# Pass32 — Section 8 (position 4): Provider Corroboration
# ---------------------------------------------------------------------------

def _build_provider_corroboration_section(
    ext: dict,
    rm: dict,
    citation_by_id: dict | None = None,
) -> MediationSection:
    """
    Surface when 2+ distinct provider entities independently document the same
    objective condition (disc, radiculopathy, stenosis, etc.).

    Distinct provider = distinct provider_entity_id from structured data.
    Same clinic / same practice / different note author = same entity.
    If provider_entity_id data is absent or ambiguous, section is skipped entirely.
    Under-trigger is the correct behavior here.
    """
    findings = (
        [f for f in (rm.get("promoted_findings") or []) if isinstance(f, dict)]
        if isinstance(rm, dict) else []
    )

    # condition_key -> set of distinct provider_entity_ids
    condition_providers: dict[str, set[str]] = {}
    # condition_key -> list of citation texts (one per provider for the output)
    condition_cites: dict[str, list[str]] = {}
    has_entity_id_data = False

    for finding in findings:
        cat = str(finding.get("category") or "").lower()
        if cat not in _OBJECTIVE_TRIGGER_CATEGORIES:
            continue
        label = _clean(finding.get("label") or "")
        if not label:
            continue

        # Resolve provider_entity_id: check finding directly, then its citations
        entity_id: str | None = (
            finding.get("provider_entity_id") or finding.get("provider_id") or None
        )
        cite_for_provider = ""
        if not entity_id:
            cids = [str(c) for c in (finding.get("citation_ids") or [])]
            for cid in cids:
                row = (citation_by_id or {}).get(cid) or {}
                eid = row.get("provider_entity_id") or row.get("provider_id")
                if eid:
                    entity_id = str(eid)
                    cite_for_provider = f"[p. {row.get('local_page') or row.get('global_page') or '?'}]"
                    break

        if not entity_id:
            continue

        has_entity_id_data = True
        # Map to a condition keyword
        m = _CORROBORATION_CONDITION_PATTERN.search(label)
        if not m:
            continue
        condition_key = m.group(0).lower()

        if condition_key not in condition_providers:
            condition_providers[condition_key] = set()
            condition_cites[condition_key] = []

        if entity_id not in condition_providers[condition_key]:
            condition_providers[condition_key].add(entity_id)
            if cite_for_provider:
                condition_cites[condition_key].append(cite_for_provider)

    # If no entity ID data available at all, skip the section
    if not has_entity_id_data:
        return MediationSection(
            key="provider_corroboration",
            title="PROVIDER CORROBORATION",
            items=[],
            gate_required=False,
        )

    # Build items for conditions with 2+ distinct provider entities
    items: list[MediationItem] = []
    for condition_key in sorted(condition_providers.keys()):
        if len(condition_providers[condition_key]) >= 2:
            cites = condition_cites.get(condition_key) or []
            support = " ".join(cites[:4])
            items.append(MediationItem(
                label=f"Multiple treating providers documented {condition_key}.",
                support=support,
            ))
            if len(items) >= 3:
                break

    corroboration_triggered = bool(items)
    return MediationSection(
        key="provider_corroboration",
        title="PROVIDER CORROBORATION",
        items=items,
        gate_required=corroboration_triggered,
        gate_fail=False,  # if triggered, items are present by construction
    )


# ---------------------------------------------------------------------------
# Pass32 — Section 9 (position 7): Current Condition & Prognosis
# ---------------------------------------------------------------------------

def _last_window_trigger(
    raw_events: list | None,
    rm: dict,
) -> bool:
    """
    True if the last documented encounter has structured signals warranting a
    Current Condition section.

    Trigger conditions (no free-text keyword matching on "persistent"):
    1. Last dated event has a non-empty diagnoses list (active diagnosis documented).
    2. Last dated event has exam_findings matching _FUNCTIONAL_PATTERN (structured pipeline categories).
    3. rm.promoted_findings contains an entry with category "referral" or a label matching
       _REFERRAL_PATTERN (pipeline-produced finding label).
    4. rm.promoted_findings contains a label matching _SURGICAL_CANDIDACY_PATTERN.
    """
    if not raw_events:
        return False

    dated = _sorted_dated_events(raw_events)
    if not dated:
        return False

    last_event, _ = dated[-1]

    # Check 1: active diagnoses on last encounter
    if getattr(last_event, "diagnoses", None):
        return True

    # Check 2: functional pattern in last encounter exam_findings (structured pipeline output)
    for fact in (getattr(last_event, "exam_findings", None) or []):
        if _FUNCTIONAL_PATTERN.search(getattr(fact, "text", "") or ""):
            return True

    # Check 3 & 4: referral or surgical candidacy in promoted_findings (pipeline-produced)
    if isinstance(rm, dict):
        for finding in (rm.get("promoted_findings") or []):
            if not isinstance(finding, dict):
                continue
            cat = str(finding.get("category") or "").lower()
            label = str(finding.get("label") or "")
            if cat == "referral" or _REFERRAL_PATTERN.search(label):
                return True
            if _SURGICAL_CANDIDACY_PATTERN.search(label):
                return True

    return False


def _build_current_condition_section(
    ext: dict,
    rm: dict,
    raw_events: list | None = None,
    event_citations_by_event: dict | None = None,
    citation_by_id: dict | None = None,
) -> MediationSection:
    """
    Surface structured findings from the last documented encounter.
    Uses last-window rule: trigger requires structured signals on the last encounter,
    not free-text keyword matching.

    Never writes "permanent" unless the structured label contains that word.
    Max 4 items.
    """
    trigger = _last_window_trigger(raw_events, rm)
    items: list[MediationItem] = []

    if trigger and raw_events:
        dated = _sorted_dated_events(raw_events)
        if dated:
            last_event, _ = dated[-1]
            last_evt_refs = (event_citations_by_event or {}).get(
                str(getattr(last_event, "event_id", "")), []
            )
            last_cite = _refs_to_citation_text(last_evt_refs)

            seen: set[str] = set()

            # Items from last event's diagnoses
            for dx in (getattr(last_event, "diagnoses", None) or []):
                dx_text = _clean(getattr(dx, "text", "") or "")
                if not dx_text or dx_text.lower() in seen:
                    continue
                seen.add(dx_text.lower())
                items.append(MediationItem(
                    label=f"Most recent records document: {dx_text}",
                    support=last_cite,
                ))
                if len(items) >= 2:
                    break

            # Items from last event's exam_findings matching functional pattern
            for fact in (getattr(last_event, "exam_findings", None) or []):
                fact_text = _clean(getattr(fact, "text", "") or "")
                if not fact_text or not _FUNCTIONAL_PATTERN.search(fact_text):
                    continue
                if fact_text.lower() in seen:
                    continue
                seen.add(fact_text.lower())
                items.append(MediationItem(
                    label=f"Ongoing restrictions documented: {fact_text}",
                    support=last_cite,
                ))
                if len(items) >= 3:
                    break

            # Items from promoted_findings: referral / surgical candidacy
            if isinstance(rm, dict) and len(items) < 4:
                for finding in (rm.get("promoted_findings") or []):
                    if not isinstance(finding, dict):
                        continue
                    label = _clean(finding.get("label") or "")
                    if not label or label.lower() in seen:
                        continue
                    cat = str(finding.get("category") or "").lower()
                    cids = [str(c) for c in (finding.get("citation_ids") or [])]
                    support = _cids_to_citation_text(cids, citation_by_id) or last_cite

                    if cat == "referral" or _REFERRAL_PATTERN.search(label):
                        seen.add(label.lower())
                        items.append(MediationItem(
                            label=f"Continued care recommendation documented: {label}",
                            support=support,
                        ))
                    elif _SURGICAL_CANDIDACY_PATTERN.search(label):
                        seen.add(label.lower())
                        items.append(MediationItem(
                            label=f"Surgical candidacy documented: {label}",
                            support=support,
                        ))

                    if len(items) >= 4:
                        break

    return MediationSection(
        key="current_condition",
        title="CURRENT CONDITION & PROGNOSIS",
        items=items,
        gate_required=trigger,
        gate_fail=trigger and not bool(items),
    )


# ---------------------------------------------------------------------------
# Pass32 — Section 10 (position 8): Clinical Course & Reasonableness
# ---------------------------------------------------------------------------

def _build_clinical_reasonableness_section(
    ext: dict,
    rm: dict,
    raw_events: list | None = None,
    event_citations_by_event: dict | None = None,
) -> MediationSection:
    """
    Deterministic escalation narrative.
    Triggers only when _detect_escalation() confirms genuine escalation pattern.
    ED + PT alone is NOT sufficient — must include imaging or higher-tier intervention.

    Items are locked templates driven by stage presence, not free text.
    Max 5 items.
    """
    stages = _detect_stages(raw_events or [], rm)
    trigger = _detect_escalation(stages)
    items: list[MediationItem] = []

    if trigger:
        stage_set = set(stages)

        # Build earliest-event citation map for this section
        stage_first_cite: dict[str, str] = {}
        if raw_events and event_citations_by_event:
            dated = _sorted_dated_events(raw_events)
            for evt, _ in dated:
                evtype = str(
                    getattr(getattr(evt, "event_type", None), "value", getattr(evt, "event_type", "")) or ""
                ).lower().strip()
                for stage, types in _STAGE_EVENT_TYPES.items():
                    if stage not in stage_first_cite and evtype in types:
                        refs = event_citations_by_event.get(str(getattr(evt, "event_id", "")), [])
                        cite = _refs_to_citation_text(refs)
                        if cite:
                            stage_first_cite[stage] = cite

        # Item 1: conservative care initiated
        conservative_present = stage_set & _CONSERVATIVE_STAGES
        if conservative_present:
            first_conservative = next(
                (s for s in _CANONICAL_STAGE_ORDER if s in conservative_present), None
            )
            if first_conservative:
                stage_label = _STAGE_LABELS.get(first_conservative, first_conservative)
                cite = stage_first_cite.get(first_conservative, "")
                items.append(MediationItem(
                    label=f"Conservative care initiated: {stage_label}.",
                    support=cite,
                ))

        # Item 2: symptoms persisted / escalation documented
        if stage_set & _ADVANCED_STAGES:
            items.append(MediationItem(label="Symptoms persisted; escalation to higher-tier care documented."))

        # Item 3: imaging
        if "imaging" in stage_set:
            cite = stage_first_cite.get("imaging", "")
            items.append(MediationItem(label="Diagnostic imaging ordered.", support=cite))

        # Item 4: specialist
        if "specialist" in stage_set:
            cite = stage_first_cite.get("specialist", "")
            items.append(MediationItem(label="Specialist consultation documented.", support=cite))

        # Item 5: procedure / surgery
        for proc_stage in ("procedure", "surgery"):
            if proc_stage in stage_set:
                label_text = (
                    "Interventional procedure documented."
                    if proc_stage == "procedure"
                    else "Surgical intervention documented."
                )
                cite = stage_first_cite.get(proc_stage, "")
                items.append(MediationItem(label=label_text, support=cite))
                break

        items = items[:5]

    return MediationSection(
        key="clinical_reasonableness",
        title="CLINICAL COURSE & REASONABLENESS",
        items=items,
        gate_required=trigger,
        gate_fail=trigger and not bool(items),
    )


# ---------------------------------------------------------------------------
# Mediation Structural Gate
# ---------------------------------------------------------------------------

def run_mediation_structural_gate(sections: list[MediationSection]) -> list[str]:
    """
    Return list of fail codes for required sections that are absent.
    Only fails on present-but-not-surfaced signals.
    Never fails on thin packets where sections were never triggered.
    """
    fail_codes: list[str] = []
    for section in sections:
        if section.gate_required and not section.items:
            fail_codes.append(f"MEDIATION_GATE_FAIL:{section.key}:required_but_absent")
    return fail_codes


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_mediation_sections(
    ext: dict,
    rm: dict,
    raw_events: list | None = None,
    event_citations_by_event: dict | None = None,
    citation_by_id: dict | None = None,
    specials_summary: dict | None = None,
    gaps: list | None = None,
) -> list[MediationSection]:
    """
    Build ordered mediation leverage sections (Pass31 + Pass32).

    Section order (10 sections):
      1. Medical Severity Profile
      2. Mechanism & Initial Presentation
      3. Objective Findings
      4. Provider Corroboration       [Pass32 — optional]
      5. Treatment Progression
      6. Functional Limitations
      7. Current Condition & Prognosis [Pass32]
      8. Clinical Course & Reasonableness [Pass32]
      9. Economic Damages Summary
     10. Anticipated Defense Arguments & Context

    Returns list of MediationSection in mandatory rendering order.
    The caller (timeline_pdf.py) iterates sections and renders each with items.
    Chronology is rendered separately by timeline_pdf.py and always follows last.
    """
    return [
        _build_severity_profile_section(ext, rm),
        _build_mechanism_section(ext, rm, raw_events, event_citations_by_event, citation_by_id),
        _build_objective_findings_section(ext, rm, citation_by_id),
        _build_provider_corroboration_section(ext, rm, citation_by_id),
        _build_treatment_progression_section(ext, rm, raw_events, event_citations_by_event, citation_by_id),
        _build_functional_limitations_section(ext, rm, citation_by_id),
        _build_current_condition_section(ext, rm, raw_events, event_citations_by_event, citation_by_id),
        _build_clinical_reasonableness_section(ext, rm, raw_events, event_citations_by_event),
        _build_economic_damages_section(ext, rm, specials_summary),
        _build_defense_preemption_section(ext, rm, gaps),
    ]
