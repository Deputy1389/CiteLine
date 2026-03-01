"""
Settlement Feature Pack v1 — single-pass feature extraction for settlement intelligence.

Centralises all clinical signal extraction so that DAM v2, CSI v1, and the Settlement Model
Report can consume a single pre-extracted dict without duplicating keyword logic.

Public API:
    build_settlement_feature_pack(evidence_graph_payload, renderer_manifest) -> dict

Returns a SettlementFeaturePack.v1 dict. Never raises.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any

logger = logging.getLogger(__name__)

# ── Keyword sets (clinical logic lives here, not in renderer) ─────────────────

_SURGERY_KW = frozenset([
    "surgery", "operative", "arthroscop", "fusion", "laminectomy",
    "discectomy", "spinal fusion", "decompression",
])
_INJECTION_KW = frozenset([
    "injection", "epidural", "esi", "depo-medrol", "nerve block",
    "steroid injection", "cortisone", "interlaminar",
])
_RADICULOPATHY_KW = frozenset(["radiculopathy", "radicular", "radiculitis"])
_DISC_HERNIATION_KW = frozenset([
    "herniation", "herniated", "disc displacement", "disc bulge", "bulge",
    "protrusion", "extruded disc",
])
_SOFT_TISSUE_KW = frozenset([
    "spasm", "strain", "sprain", "soft tissue", "contusion", "myalgia",
    "muscle spasm", "cervical strain", "lumbar strain",
])
_NEURO_DEFICIT_KW = frozenset([
    "radiculopathy", "neuropathy", "deficit", "numbness", "tingling",
    "paresthesia", "weakness", "sensory loss",
])
_SPECIALIST_KW = frozenset([
    "orthopedic", "orthopaedic", "neurosurgeon", "neurologist",
    "spine specialist", "pain management", "pain specialist", "physiatrist",
])
_SURGICAL_INDICATION_KW = [
    "surgical candidate", "recommend surgery", "surgery indicated",
    "surgery recommended", "candidate for surgery", "surgical intervention",
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_date(s: str | None) -> _date | None:
    if not s:
        return None
    try:
        parts = str(s).split("-")
        if len(parts) == 3:
            return _date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        pass
    return None


def _event_type_str(event: dict) -> str:
    raw = event.get("event_type")
    if isinstance(raw, dict):
        return str(raw.get("value") or "").lower()
    return str(raw or "").lower()


def _event_all_text(event: dict) -> str:
    parts: list[str] = []
    for k in ("reason_for_visit", "chief_complaint", "author_name", "author_role"):
        v = event.get(k)
        if v:
            parts.append(str(v))
    for k in ("facts", "diagnoses", "procedures", "exam_findings", "treatment_plan"):
        for f in (event.get(k) or []):
            if isinstance(f, dict):
                parts.append(str(f.get("text") or ""))
            else:
                parts.append(str(f))
    return " ".join(parts).lower()


def _kw_in(text: str, kws: frozenset) -> bool:
    return any(kw in text for kw in kws)


def _pf_label(pf: dict) -> str:
    return str(pf.get("label") or "").lower()


def _empty_pack() -> dict[str, Any]:
    return {
        "schema_version": "sfp.v1",
        "has_surgery": False,
        "has_injection": False,
        "has_fracture": False,
        "has_mri_positive": False,
        "has_radiculopathy": False,
        "has_disc_herniation": False,
        "has_soft_tissue": False,
        "has_emg_positive": False,
        "has_ed_visit": False,
        "has_imaging": False,
        "has_pt": False,
        "has_specialist": False,
        "pt_total_encounters": None,
        "pt_date_start": None,
        "pt_date_end": None,
        "treatment_duration_days": None,
        "gaps": [],
        "max_gap_days": 0,
        "gap_count_over_30": 0,
        "largest_gap": None,
        "has_prior_similar_injury": False,
        "doi": None,
        "first_event_date": None,
        "days_to_first_treatment": None,
        "promoted_findings": [],
        "imaging_promoted_findings": [],
        "has_neuro_deficit_keywords": False,
        "has_surgical_indication": False,
    }


# ── Main extractor ────────────────────────────────────────────────────────────

def _build(eg: dict | None, rm: dict | None) -> dict[str, Any]:
    eg = eg if isinstance(eg, dict) else {}
    rm = rm if isinstance(rm, dict) else {}

    events: list[dict] = [e for e in (eg.get("events") or []) if isinstance(e, dict)]
    gaps: list[dict] = [g for g in (eg.get("gaps") or []) if isinstance(g, dict)]
    promoted_findings: list[dict] = [
        pf for pf in (rm.get("promoted_findings") or []) if isinstance(pf, dict)
    ]
    extensions: dict = eg.get("extensions") if isinstance(eg.get("extensions"), dict) else {}

    # ── Procedure / treatment signals from events ─────────────────────────────
    has_surgery = False
    has_injection = False
    has_ed_visit = False
    has_imaging = False
    has_pt = False
    has_specialist = False
    has_prior_similar_injury = False
    has_emg_positive = False

    for ev in events:
        et = _event_type_str(ev)
        txt = _event_all_text(ev)

        if et == "procedure":
            if _kw_in(txt, _SURGERY_KW):
                has_surgery = True
            if _kw_in(txt, _INJECTION_KW):
                has_injection = True

        if "ed" in et or "emergency" in et:
            has_ed_visit = True

        if "imaging" in et or "radiology" in et or "xray" in et or "mri" in et or "ct" in et:
            has_imaging = True

        if "physical_therapy" in et or "pt_visit" in et or "therapy" in et:
            has_pt = True

        if et == "referenced_prior_event":
            has_prior_similar_injury = True

        if _kw_in(txt, _SPECIALIST_KW):
            has_specialist = True

        if "emg" in et or ("imaging" in et and "emg" in txt):
            has_emg_positive = True

    # Check contradiction_matrix in extensions for prior injury
    for entry in (extensions.get("contradiction_matrix") or []):
        if isinstance(entry, dict) and entry.get("body_region"):
            has_prior_similar_injury = True
            break

    # ── Promoted findings analysis ────────────────────────────────────────────
    imaging_pf: list[dict] = []
    has_fracture = False
    has_mri_positive = False
    has_radiculopathy = False
    has_disc_herniation = False
    has_soft_tissue = False
    has_neuro_deficit_keywords = False
    has_surgical_indication = False

    for pf in promoted_findings:
        label = _pf_label(pf)
        category = str(pf.get("category") or "").lower()
        polarity = str(pf.get("finding_polarity") or "").lower()

        if category == "imaging":
            imaging_pf.append(pf)
            has_imaging = True
            if polarity == "positive":
                has_mri_positive = True

        if "fracture" in label:
            has_fracture = True

        if _kw_in(label, _RADICULOPATHY_KW):
            has_radiculopathy = True
            has_neuro_deficit_keywords = True

        if _kw_in(label, _DISC_HERNIATION_KW):
            has_disc_herniation = True

        if _kw_in(label, _SOFT_TISSUE_KW):
            has_soft_tissue = True

        if _kw_in(label, _NEURO_DEFICIT_KW):
            has_neuro_deficit_keywords = True

        if "emg" in label:
            has_emg_positive = True

        if any(kw in label for kw in _SURGICAL_INDICATION_KW):
            has_surgical_indication = True

    # Also scan events for radiculopathy / disc / neuro keywords
    for ev in events:
        txt = _event_all_text(ev)
        if _kw_in(txt, _RADICULOPATHY_KW):
            has_radiculopathy = True
            has_neuro_deficit_keywords = True
        if _kw_in(txt, _NEURO_DEFICIT_KW):
            has_neuro_deficit_keywords = True
        if _kw_in(txt, _DISC_HERNIATION_KW):
            has_disc_herniation = True
        if _kw_in(txt, _SOFT_TISSUE_KW):
            has_soft_tissue = True

    # ── PT summary ────────────────────────────────────────────────────────────
    pt_summary = rm.get("pt_summary") if isinstance(rm.get("pt_summary"), dict) else {}
    pt_total_encounters: int | None = None
    pt_date_start: str | None = None
    pt_date_end: str | None = None
    treatment_duration_days: int | None = None

    if pt_summary:
        total = pt_summary.get("total_encounters")
        if total is not None:
            try:
                pt_total_encounters = int(total)
                if pt_total_encounters > 0:
                    has_pt = True
            except Exception:
                pass

        pt_date_start = pt_summary.get("date_start") or None
        pt_date_end = pt_summary.get("date_end") or None

        d_start = _parse_date(pt_date_start)
        d_end = _parse_date(pt_date_end)
        if d_start and d_end:
            treatment_duration_days = (d_end - d_start).days

    # ── Gaps ──────────────────────────────────────────────────────────────────
    max_gap_days = 0
    gap_count_over_30 = 0
    largest_gap: dict | None = None

    for g in gaps:
        try:
            days = int(g.get("duration_days") or 0)
        except Exception:
            days = 0
        if days > 30:
            gap_count_over_30 += 1
        if days > max_gap_days:
            max_gap_days = days
            largest_gap = g

    # ── Date of injury and first treatment ────────────────────────────────────
    doi_str: str | None = rm.get("doi") or rm.get("date_of_injury") or None
    if not doi_str and isinstance(rm.get("case_metadata"), dict):
        doi_str = (
            rm["case_metadata"].get("doi")
            or rm["case_metadata"].get("date_of_injury")
        )

    event_dates: list[_date] = []
    for ev in events:
        raw_date = ev.get("date") or ev.get("event_date")
        if isinstance(raw_date, dict):
            raw_date = raw_date.get("value")
        d = _parse_date(str(raw_date) if raw_date else None)
        if d:
            event_dates.append(d)

    first_event_date: str | None = None
    days_to_first_treatment: int | None = None

    if event_dates:
        first_date = min(event_dates)
        first_event_date = first_date.isoformat()
        doi_parsed = _parse_date(doi_str)
        if doi_parsed:
            days_to_first_treatment = (first_date - doi_parsed).days

    return {
        "schema_version": "sfp.v1",
        "has_surgery": has_surgery,
        "has_injection": has_injection,
        "has_fracture": has_fracture,
        "has_mri_positive": has_mri_positive,
        "has_radiculopathy": has_radiculopathy,
        "has_disc_herniation": has_disc_herniation,
        "has_soft_tissue": has_soft_tissue,
        "has_emg_positive": has_emg_positive,
        "has_ed_visit": has_ed_visit,
        "has_imaging": has_imaging,
        "has_pt": has_pt,
        "has_specialist": has_specialist,
        "pt_total_encounters": pt_total_encounters,
        "pt_date_start": pt_date_start,
        "pt_date_end": pt_date_end,
        "treatment_duration_days": treatment_duration_days,
        "gaps": [dict(g) for g in gaps],
        "max_gap_days": max_gap_days,
        "gap_count_over_30": gap_count_over_30,
        "largest_gap": dict(largest_gap) if largest_gap else None,
        "has_prior_similar_injury": has_prior_similar_injury,
        "doi": doi_str,
        "first_event_date": first_event_date,
        "days_to_first_treatment": days_to_first_treatment,
        "promoted_findings": promoted_findings,
        "imaging_promoted_findings": imaging_pf,
        "has_neuro_deficit_keywords": has_neuro_deficit_keywords,
        "has_surgical_indication": has_surgical_indication,
    }


def build_settlement_feature_pack(
    evidence_graph_payload: dict | None,
    renderer_manifest: dict | None,
) -> dict[str, Any]:
    """
    Extract all features needed by DAM v2, CSI v1, and the Settlement Model Report.

    Parameters
    ----------
    evidence_graph_payload
        JSON-serialised EvidenceGraph dict or None.
    renderer_manifest
        JSON-serialised RendererManifest dict or None.

    Returns
    -------
    dict
        SettlementFeaturePack.v1 schema. Never raises.
    """
    try:
        eg = evidence_graph_payload if isinstance(evidence_graph_payload, dict) else None
        rm = renderer_manifest if isinstance(renderer_manifest, dict) else None
        return _build(eg, rm)
    except Exception as exc:
        logger.exception(f"SettlementFeaturePack build failed: {exc}")
        return _empty_pack()
