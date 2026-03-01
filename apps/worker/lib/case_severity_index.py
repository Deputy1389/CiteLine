"""
Case Severity Index v2 - deterministic valuation signal.

Computes base and risk-adjusted CSI from structured evidence/manifest data only.
No LLM, no gate mutation, no renderer inference.
"""
from __future__ import annotations

from datetime import date, datetime
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_WEIGHTS = {"objective": 0.45, "intensity": 0.35, "duration": 0.20}

_NEGATIVE_IMAGING_PATTERNS = [
    re.compile(r"\bno acute\b", re.I),
    re.compile(r"\bunremarkable\b", re.I),
    re.compile(r"\bno fracture\b", re.I),
    re.compile(r"\bno dislocation\b", re.I),
]


def _safe_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _parse_iso_date(v: Any) -> date | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        # Normalize datetime to date
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _duration_bucket(start_iso: Any, end_iso: Any) -> tuple[int, str, str]:
    start = _parse_iso_date(start_iso)
    end = _parse_iso_date(end_iso)
    if not start or not end:
        return 3, "duration_missing", "Duration not fully documented"
    if end < start:
        return 3, "duration_invalid", "Duration not fully documented"
    days = (end - start).days
    if days < 14:
        return 1, "lt_14", "<14 day treatment course"
    if days <= 60:
        return 3, "15_60", "15-60 day treatment course"
    if days <= 180:
        return 6, "61_180", "61-180 day treatment course"
    return 9, "gt_180", ">180 day treatment course"


def _labels_by_category(promoted: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for pf in promoted:
        if not isinstance(pf, dict):
            continue
        cat = str(pf.get("category") or "").strip().lower()
        lbl = str(pf.get("label") or "").strip()
        if not cat or not lbl:
            continue
        out.setdefault(cat, []).append(lbl)
    return out


def _citation_ids_by_category(promoted: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for pf in promoted:
        if not isinstance(pf, dict):
            continue
        cat = str(pf.get("category") or "").strip().lower()
        if not cat:
            continue
        ids = {str(c).strip() for c in _safe_list(pf.get("citation_ids")) if str(c).strip()}
        if ids:
            out.setdefault(cat, set()).update(ids)
    return out


def _has_any(labels: list[str], pat: str) -> bool:
    rx = re.compile(pat, re.I)
    return any(rx.search(x or "") for x in labels)


def _objective_component(feature_pack: dict[str, Any], promoted: list[dict[str, Any]]) -> tuple[int, str, str, set[str]]:
    by_cat = _labels_by_category(promoted)
    cids = _citation_ids_by_category(promoted)

    imaging_labels = by_cat.get("imaging", [])
    dx_labels = by_cat.get("diagnosis", [])
    obj_labels = by_cat.get("objective_deficit", [])
    proc_labels = by_cat.get("procedure", [])

    has_surgical_indication = bool(feature_pack.get("has_surgery", False)) or _has_any(proc_labels, r"\b(surgery|operative|fusion|arthroscop)\b")
    if has_surgical_indication:
        return 10, "surgical_indication", "Surgical indication documented", set(cids.get("procedure", set()))

    has_radic = bool(feature_pack.get("has_radiculopathy", False)) or _has_any(dx_labels + imaging_labels + obj_labels, r"\bradicul\w*\b")
    if has_radic:
        return 8, "radiculopathy", "Radiculopathy documented", set(cids.get("diagnosis", set()) | cids.get("imaging", set()) | cids.get("objective_deficit", set()))

    has_disc = bool(feature_pack.get("has_disc_herniation", False)) or _has_any(dx_labels + imaging_labels, r"\b(disc|herniat|protrusion|foramin|stenosis|displacement)\b")
    if has_disc:
        return 7, "disc_displacement", "Disc pathology documented", set(cids.get("imaging", set()) | cids.get("diagnosis", set()))

    has_soft = bool(feature_pack.get("has_soft_tissue", False)) or _has_any(obj_labels + dx_labels + imaging_labels, r"\b(spasm|straightening|lordosis|strain|sprain|tenderness|soft tissue)\b")
    if has_soft:
        return 4, "soft_tissue", "Soft tissue / spasm documented", set(cids.get("objective_deficit", set()) | cids.get("diagnosis", set()) | cids.get("imaging", set()))

    has_imaging = bool(feature_pack.get("has_imaging", False)) or bool(imaging_labels)
    if has_imaging:
        neg_only = bool(imaging_labels) and all(any(p.search(lbl or "") for p in _NEGATIVE_IMAGING_PATTERNS) for lbl in imaging_labels)
        if neg_only:
            return 1, "imaging_negative_only", "Imaging negative for acute findings", set(cids.get("imaging", set()))
        return 1, "imaging_no_objective", "Imaging present without objective pathology tier", set(cids.get("imaging", set()))

    return 1, "no_objective", "No objective imaging findings documented", set()


def _intensity_component(feature_pack: dict[str, Any], rm: dict[str, Any], promoted: list[dict[str, Any]]) -> tuple[int, str, str, set[str]]:
    cids = _citation_ids_by_category(promoted)
    pt_cids = {str(c).strip() for c in _safe_list(_safe_dict(rm.get("pt_summary")).get("citation_ids")) if str(c).strip()}
    ed_cids = {
        str(c).strip()
        for c in _safe_list(_safe_dict(_safe_dict(rm.get("bucket_evidence")).get("ed")).get("citation_ids"))
        if str(c).strip()
    }

    has_surgery = bool(feature_pack.get("has_surgery", False))
    has_injection = bool(feature_pack.get("has_injection", False))
    has_specialist = bool(feature_pack.get("has_specialist", False))
    has_ed = bool(feature_pack.get("has_ed_visit", False)) or bool(ed_cids)
    has_imaging = bool(feature_pack.get("has_imaging", False)) or bool(cids.get("imaging", set()))
    pt = _safe_dict(rm.get("pt_summary"))
    has_pt = bool(feature_pack.get("has_pt", False)) or bool(pt.get("total_encounters") or pt.get("date_start") or pt.get("date_end"))

    if has_surgery:
        return 10, "surgery", "Surgery-level intervention documented", set(cids.get("procedure", set()))
    if has_injection or has_specialist:
        return 8, "injection_specialist", "Injection / specialist intervention documented", set(cids.get("procedure", set()) | cids.get("treatment", set()))
    if has_ed and has_imaging and has_pt:
        return 6, "ed_imaging_pt", "ED + imaging + PT course documented", set(ed_cids | cids.get("imaging", set()) | pt_cids)
    if has_ed and has_pt:
        return 4, "ed_pt", "ED + PT course documented", set(ed_cids | pt_cids)
    if has_ed:
        return 1, "ed_only", "ED-only treatment documented", set(ed_cids)
    return 1, "none", "No treatment intensity tier documented", set()


def _duration_component(rm: dict[str, Any]) -> tuple[int, str, str, set[str], Any, Any]:
    pt = _safe_dict(rm.get("pt_summary"))
    score, tier, label = _duration_bucket(pt.get("date_start"), pt.get("date_end"))
    cids = {str(c).strip() for c in _safe_list(pt.get("citation_ids")) if str(c).strip()}
    return score, tier, label, cids, pt.get("date_start"), pt.get("date_end")


def _risk_inputs(eg: dict[str, Any], feature_pack: dict[str, Any]) -> tuple[float, list[str], dict[str, Any]]:
    ext = _safe_dict(eg.get("extensions"))
    lsv1 = _safe_dict(ext.get("litigation_safe_v1"))
    dap = _safe_dict(ext.get("defense_attack_paths"))

    max_gap_days = lsv1.get("max_gap_days")
    has_prior = dap.get("has_prior_similar_injury")
    days_to_first_care = lsv1.get("days_to_first_care")

    # Keep deterministic fallbacks from feature pack if extensions keys are absent.
    if max_gap_days is None:
        max_gap_days = feature_pack.get("max_gap_days")
    if has_prior is None:
        has_prior = feature_pack.get("has_prior_similar_injury")

    penalty = 0.0
    factors: list[str] = []

    try:
        if max_gap_days is not None and float(max_gap_days) > 60:
            penalty += 0.5
            factors.append("care_gap_over_60_days")
    except Exception:
        pass

    if bool(has_prior):
        penalty += 0.5
        factors.append("prior_similar_injury")

    try:
        if days_to_first_care is not None and float(days_to_first_care) > 14:
            penalty += 0.3
            factors.append("delayed_first_care_over_14_days")
    except Exception:
        pass

    penalty = min(1.0, round(penalty, 1))
    inputs_used = {
        "max_gap_days": max_gap_days,
        "has_prior_similar_injury": bool(has_prior),
        "days_to_first_care": days_to_first_care,
    }
    return penalty, factors, inputs_used


def _band_for_csi(csi: float) -> str:
    if csi <= 3.4:
        return "Minor soft tissue"
    if csi <= 5.4:
        return "Moderate soft tissue"
    if csi <= 6.9:
        return "Moderate soft tissue with objective support"
    if csi <= 8.4:
        return "Injection-tier profile"
    return "Surgical-tier profile"


def _resolve_page_refs(citation_ids: set[str], eg: dict[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for c in _safe_list(eg.get("citations")):
        if not isinstance(c, dict):
            continue
        cid = str(c.get("citation_id") or "").strip()
        if cid:
            by_id[cid] = c
    refs: list[dict[str, Any]] = []
    for cid in sorted(citation_ids):
        c = by_id.get(cid)
        if not c:
            continue
        try:
            p = int(c.get("page_number") or 0)
        except Exception:
            p = 0
        if p <= 0:
            continue
        refs.append({
            "source_document_id": str(c.get("source_document_id") or "").strip() or None,
            "page_number": p,
        })
    refs.sort(key=lambda x: (str(x.get("source_document_id") or ""), int(x.get("page_number") or 0)))
    # dedupe
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for r in refs:
        k = (str(r.get("source_document_id") or ""), int(r.get("page_number") or 0))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def build_case_severity_index(
    evidence_graph_payload: dict | None,
    renderer_manifest: dict | None,
    feature_pack: dict | None = None,
) -> dict[str, Any]:
    """Build deterministic CSI v2 contract.

    Backward compatibility fields are retained:
    - case_severity_index
    - duration_score, treatment_intensity_score, objective_finding_score
    - component_labels
    """
    try:
        eg = _safe_dict(evidence_graph_payload)
        rm = _safe_dict(renderer_manifest)
        fp = _safe_dict(feature_pack)

        promoted = [x for x in _safe_list(rm.get("promoted_findings")) if isinstance(x, dict)]

        d_score, d_tier, d_label, d_cids, d_start, d_end = _duration_component(rm)
        i_score, i_tier, i_label, i_cids = _intensity_component(fp, rm, promoted)
        o_score, o_tier, o_label, o_cids = _objective_component(fp, promoted)

        base_raw = (o_score * _WEIGHTS["objective"]) + (i_score * _WEIGHTS["intensity"]) + (d_score * _WEIGHTS["duration"])
        base_csi = round(base_raw, 1)

        ceiling_applied = False
        floor_applied = False

        has_surgery = i_tier == "surgery"
        has_injection_or_surgery = i_tier in {"surgery", "injection_specialist"}

        if has_surgery and base_csi < 8.5:
            base_csi = 8.5
            ceiling_applied = True

        if (not has_injection_or_surgery) and o_score <= 1 and base_csi > 5.5:
            base_csi = 5.5
            floor_applied = True

        penalty, risk_factors, risk_inputs = _risk_inputs(eg, fp)
        risk_adjusted = max(0.0, round(base_csi - penalty, 1))

        support_cids = set(sorted(d_cids | i_cids | o_cids))
        support_page_refs = _resolve_page_refs(support_cids, eg)

        band = _band_for_csi(base_csi)
        profile = f"Profile: {o_label}; {i_label}; {d_label}."

        result = {
            "schema_version": "csi.v2",
            "base_csi": base_csi,
            "risk_adjusted_csi": risk_adjusted,
            "score_0_100": int(base_csi * 10),
            "weights": dict(_WEIGHTS),
            "component_scores": {
                "objective": {"score": o_score, "tier_key": o_tier, "label": o_label},
                "intensity": {"score": i_score, "tier_key": i_tier, "label": i_label},
                "duration": {"score": d_score, "tier_key": d_tier, "label": d_label},
            },
            "selected_tiers": {
                "objective": o_tier,
                "intensity": i_tier,
                "duration": d_tier,
            },
            "floor_applied": floor_applied,
            "ceiling_applied": ceiling_applied,
            "risk_penalty": penalty,
            "risk_factors": risk_factors,
            "band": band,
            "profile": profile,
            "support": {
                "citation_ids": sorted(support_cids),
                "page_refs": support_page_refs,
            },
            "inputs_used": {
                "date_start": d_start,
                "date_end": d_end,
                "signals_present": {
                    "promoted_findings": bool(promoted),
                    "pt_summary": bool(_safe_dict(rm.get("pt_summary"))),
                    "feature_pack": bool(fp),
                },
                "risk_signals": risk_inputs,
            },

            # Backward-compatibility fields
            "case_severity_index": base_csi,
            "duration_score": d_score,
            "treatment_intensity_score": i_score,
            "objective_finding_score": o_score,
            "component_labels": {
                "duration": d_label,
                "treatment_intensity": i_label,
                "objective_finding": o_label,
            },
        }
        return result
    except Exception as exc:
        logger.exception("CaseSeverityIndex build failed: %s", exc)
        return {
            "schema_version": "csi.v2",
            "base_csi": 0.0,
            "risk_adjusted_csi": 0.0,
            "score_0_100": 0,
            "weights": dict(_WEIGHTS),
            "component_scores": {
                "objective": {"score": 1, "tier_key": "no_objective", "label": "No objective imaging findings documented"},
                "intensity": {"score": 1, "tier_key": "none", "label": "No treatment intensity tier documented"},
                "duration": {"score": 3, "tier_key": "duration_missing", "label": "Duration not fully documented"},
            },
            "selected_tiers": {"objective": "no_objective", "intensity": "none", "duration": "duration_missing"},
            "floor_applied": False,
            "ceiling_applied": False,
            "risk_penalty": 0.0,
            "risk_factors": [],
            "band": "Minor soft tissue",
            "profile": "Profile: No objective imaging findings documented; No treatment intensity tier documented; Duration not fully documented.",
            "support": {"citation_ids": [], "page_refs": []},
            "inputs_used": {"date_start": None, "date_end": None, "signals_present": {}, "risk_signals": {}},

            # Backward-compatibility fields
            "case_severity_index": 0.0,
            "duration_score": 3,
            "treatment_intensity_score": 1,
            "objective_finding_score": 1,
            "component_labels": {
                "duration": "Duration not fully documented",
                "treatment_intensity": "No treatment intensity tier documented",
                "objective_finding": "No objective imaging findings documented",
            },
            "error": str(exc),
        }
