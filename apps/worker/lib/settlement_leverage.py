"""
Settlement Leverage Model v1 — deterministic, citation-bound leverage scoring.

Public API:
    build_settlement_leverage_model(evidence_graph_payload, renderer_manifest) -> dict

All inputs are dict (JSON-serialised EvidenceGraph / RendererManifest).
If either dict is None or empty all medical signals resolve as UNKNOWN (value=None).
The function never raises — it always returns a valid output dict.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any

from packages.shared.models.domain import (
    SettlementLeverageModel,
    SlmProvenance,
    SlmSignalAudit,
)

logger = logging.getLogger(__name__)

# ── Surgery / injection / hardware keyword sets ───────────────────────────────

_SURGERY_KW = frozenset(["surgery", "operative", "arthroscop", "fusion"])
_INJECTION_KW = frozenset(["injection", "epidural", "esi", "depo-medrol"])
_HARDWARE_KW = frozenset(["hardware", "implant", "screw", "rod", "plate"])
_FUTURE_SURGERY_KW = [
    "surgical candidate", "recommend surgery", "surgery indicated",
    "surgery recommended", "candidate for surgery",
]
_IMPAIRMENT_KW = ["impairment rating", "permanent impairment", "% impairment"]

# Provenance confidence → numeric weight
_CONF_WEIGHTS: dict[str, float] = {"HIGH": 1.0, "MED": 0.85, "LOW": 0.65}


# ── Shared helpers ────────────────────────────────────────────────────────────

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _is_empty(d: dict | None) -> bool:
    return not d  # None or {}


def _kw_in_text(text: str, kws: frozenset | list) -> bool:
    return any(kw in text for kw in kws)


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


def _not_det(conf: str = "MED") -> SlmSignalAudit:
    return SlmSignalAudit(
        value=None,
        provenance=SlmProvenance(source_type="not_determinable", confidence=conf),  # type: ignore[arg-type]
    )


# ── Signal extractors ─────────────────────────────────────────────────────────

def _extract_mri_positive(rm: dict, rm_absent: bool) -> SlmSignalAudit:
    if rm_absent:
        return _not_det()
    for pf in (rm.get("promoted_findings") or []):
        if not isinstance(pf, dict):
            continue
        if (
            str(pf.get("category") or "").lower() == "imaging"
            and str(pf.get("finding_polarity") or "").lower() == "positive"
        ):
            conf = "HIGH" if pf.get("citation_ids") else "MED"
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="promoted_finding", confidence=conf),  # type: ignore[arg-type]
            )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="promoted_finding", confidence="MED"),
    )


def _extract_emg_positive(eg: dict, rm: dict, data_absent: bool) -> SlmSignalAudit:
    if data_absent:
        return _not_det()
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        if _event_type_str(ev) == "imaging_study" and "emg" in _event_all_text(ev):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="event", confidence="MED"),
            )
    for pf in (rm.get("promoted_findings") or []):
        if not isinstance(pf, dict):
            continue
        if "emg" in str(pf.get("label") or "").lower():
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="promoted_finding", confidence="MED"),
            )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="event", confidence="MED"),
    )


def _extract_fracture(eg: dict, rm: dict, data_absent: bool) -> SlmSignalAudit:
    if data_absent:
        return _not_det()
    for pf in (rm.get("promoted_findings") or []):
        if not isinstance(pf, dict):
            continue
        label = str(pf.get("label") or "").lower()
        if "fracture" in label:
            conf = "HIGH" if pf.get("citation_ids") else "MED"
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="promoted_finding", confidence=conf),  # type: ignore[arg-type]
            )
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        if "fracture" in _event_all_text(ev):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="event", confidence="MED"),
            )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="promoted_finding", confidence="MED"),
    )


def _extract_surgery_performed(eg: dict, eg_absent: bool) -> SlmSignalAudit:
    if eg_absent:
        return _not_det()
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        if _event_type_str(ev) == "procedure" and _kw_in_text(_event_all_text(ev), _SURGERY_KW):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="event", confidence="HIGH"),
            )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="event", confidence="HIGH"),
    )


def _extract_injection_performed(eg: dict, rm: dict, data_absent: bool) -> SlmSignalAudit:
    if data_absent:
        return _not_det()
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        if _event_type_str(ev) == "procedure" and _kw_in_text(_event_all_text(ev), _INJECTION_KW):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="event", confidence="HIGH"),
            )
    for pf in (rm.get("promoted_findings") or []):
        if not isinstance(pf, dict):
            continue
        if _kw_in_text(str(pf.get("label") or "").lower(), _INJECTION_KW):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="promoted_finding", confidence="HIGH"),
            )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="event", confidence="HIGH"),
    )


def _extract_hardware_implanted(eg: dict, eg_absent: bool) -> SlmSignalAudit:
    if eg_absent:
        return _not_det("MED")
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        if _event_type_str(ev) == "procedure" and _kw_in_text(_event_all_text(ev), _HARDWARE_KW):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="event", confidence="MED"),
            )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="event", confidence="MED"),
    )


def _extract_total_visits(rm: dict, rm_absent: bool) -> SlmSignalAudit:
    if rm_absent:
        return _not_det()
    pt = rm.get("pt_summary")
    if not isinstance(pt, dict):
        return SlmSignalAudit(
            value=None,
            provenance=SlmProvenance(source_type="pt_summary", confidence="MED"),
        )
    total = pt.get("total_encounters")
    if total is None:
        return SlmSignalAudit(
            value=None,
            provenance=SlmProvenance(source_type="pt_summary", confidence="MED"),
        )
    conf = "HIGH" if str(pt.get("count_source") or "").lower() == "structured" else "MED"
    return SlmSignalAudit(
        value=int(total),
        provenance=SlmProvenance(source_type="pt_summary", confidence=conf),  # type: ignore[arg-type]
    )


def _extract_treatment_duration_days(rm: dict, rm_absent: bool) -> SlmSignalAudit:
    if rm_absent:
        return _not_det()
    pt = rm.get("pt_summary")
    if not isinstance(pt, dict):
        return SlmSignalAudit(
            value=None,
            provenance=SlmProvenance(source_type="pt_summary", confidence="MED"),
        )
    d_start = _parse_date(pt.get("date_start"))
    d_end = _parse_date(pt.get("date_end"))
    if d_start is None or d_end is None:
        return SlmSignalAudit(
            value=None,
            provenance=SlmProvenance(source_type="pt_summary", confidence="MED"),
        )
    return SlmSignalAudit(
        value=(d_end - d_start).days,
        provenance=SlmProvenance(source_type="pt_summary", confidence="MED"),
    )


def _extract_gap_over_30_days(eg: dict, eg_absent: bool) -> SlmSignalAudit:
    if eg_absent:
        return _not_det()
    for g in (eg.get("gaps") or []):
        if not isinstance(g, dict):
            continue
        try:
            if int(g.get("duration_days") or 0) > 30:
                return SlmSignalAudit(
                    value=True,
                    provenance=SlmProvenance(source_type="gap", confidence="HIGH"),
                )
        except Exception:
            pass
    # Determinable: empty gap list means no gap > 30d
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="gap", confidence="HIGH"),
    )


def _extract_compliance_rate(eg: dict, eg_absent: bool) -> SlmSignalAudit:
    if eg_absent:
        return _not_det("LOW")
    large_gaps = sum(
        1 for g in (eg.get("gaps") or [])
        if isinstance(g, dict) and int(g.get("duration_days") or 0) > 30
    )
    rate = max(0.5, clamp01(0.95 - 0.15 * large_gaps))
    return SlmSignalAudit(
        value=rate,
        provenance=SlmProvenance(source_type="pt_summary", confidence="LOW"),
    )


def _extract_similar_body_part_prior(eg: dict, eg_absent: bool) -> SlmSignalAudit:
    if eg_absent:
        return _not_det()
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        if _event_type_str(ev) == "referenced_prior_event":
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="event", confidence="MED"),
            )
    # Also check contradiction_matrix in extensions
    exts = eg.get("extensions") if isinstance(eg.get("extensions"), dict) else {}
    for entry in (exts.get("contradiction_matrix") or []):
        if isinstance(entry, dict) and entry.get("body_region"):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="extension", confidence="MED"),
            )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="event", confidence="MED"),
    )


def _extract_documentation_overlap_score(eg: dict, eg_absent: bool) -> SlmSignalAudit:
    if eg_absent:
        return _not_det()
    exts = eg.get("extensions") if isinstance(eg.get("extensions"), dict) else {}
    cca = exts.get("claim_context_alignment")
    if not isinstance(cca, dict):
        return SlmSignalAudit(
            value=None,
            provenance=SlmProvenance(source_type="extension", confidence="MED"),
        )
    total = cca.get("claims_total")
    fail_count = cca.get("claims_fail")
    if total is None:
        # Derive from failures list length if explicit counts absent
        failures = cca.get("failures") or []
        if not failures:
            return SlmSignalAudit(
                value=None,
                provenance=SlmProvenance(source_type="extension", confidence="MED"),
            )
        total = len(failures)
        fail_count = sum(1 for f in failures if isinstance(f, dict) and str(f.get("severity") or "").upper() in {"BLOCKED", "REVIEW_REQUIRED"})
    try:
        t = int(total)
        f = int(fail_count or 0)
        if t == 0:
            return SlmSignalAudit(
                value=None,
                provenance=SlmProvenance(source_type="extension", confidence="MED"),
            )
        return SlmSignalAudit(
            value=f / t,
            provenance=SlmProvenance(source_type="extension", confidence="MED"),
        )
    except Exception:
        return SlmSignalAudit(
            value=None,
            provenance=SlmProvenance(source_type="extension", confidence="MED"),
        )


def _extract_future_surgery_recommended(eg: dict, rm: dict, data_absent: bool) -> SlmSignalAudit:
    if data_absent:
        return _not_det()
    for pf in (rm.get("promoted_findings") or []):
        if not isinstance(pf, dict):
            continue
        if _kw_in_text(str(pf.get("label") or "").lower(), _FUTURE_SURGERY_KW):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="promoted_finding", confidence="MED"),
            )
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        if _kw_in_text(_event_all_text(ev), _FUTURE_SURGERY_KW):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="event", confidence="MED"),
            )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="promoted_finding", confidence="MED"),
    )


def _extract_impairment_rating_present(eg: dict, eg_absent: bool) -> SlmSignalAudit:
    if eg_absent:
        return _not_det()
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        if _kw_in_text(_event_all_text(ev), _IMPAIRMENT_KW):
            return SlmSignalAudit(
                value=True,
                provenance=SlmProvenance(source_type="event", confidence="MED"),
            )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="event", confidence="MED"),
    )


def _extract_documented_wage_loss(eg: dict, eg_absent: bool) -> SlmSignalAudit:
    if eg_absent:
        return _not_det()
    exts = eg.get("extensions") if isinstance(eg.get("extensions"), dict) else {}
    ss = exts.get("specials_summary")
    if isinstance(ss, dict) and ss.get("wage_loss"):
        return SlmSignalAudit(
            value=True,
            provenance=SlmProvenance(source_type="extension", confidence="MED"),
        )
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        et = _event_type_str(ev)
        if "work" in et or "employment" in et:
            txt = _event_all_text(ev)
            if any(kw in txt for kw in ("$", "wage", "income", "salary")):
                return SlmSignalAudit(
                    value=True,
                    provenance=SlmProvenance(source_type="event", confidence="MED"),
                )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="extension", confidence="MED"),
    )


def _extract_lost_work_days(eg: dict, eg_absent: bool) -> SlmSignalAudit:
    if eg_absent:
        return _not_det("LOW")
    for ev in (eg.get("events") or []):
        if not isinstance(ev, dict):
            continue
        if "work" in _event_type_str(ev):
            txt = _event_all_text(ev)
            if any(kw in txt for kw in ("restricted", "unable to work", "off work", "out of work", "work restriction")):
                return SlmSignalAudit(
                    value=True,
                    provenance=SlmProvenance(source_type="event", confidence="LOW"),
                )
    return SlmSignalAudit(
        value=False,
        provenance=SlmProvenance(source_type="event", confidence="LOW"),
    )


# ── Signal assembly ───────────────────────────────────────────────────────────

def _extract_all_signals(eg: dict | None, rm: dict | None) -> dict[str, SlmSignalAudit]:
    eg_absent = _is_empty(eg)
    rm_absent = _is_empty(rm)
    data_absent = eg_absent and rm_absent

    eg = eg or {}
    rm = rm or {}

    # Liability signals — never determinable from medical records
    _nd = _not_det()
    signals: dict[str, SlmSignalAudit] = {
        "police_report_support": _nd,
        "independent_witness": _nd,
        "comparative_fault_risk": _nd,
    }

    signals["mri_positive"] = _extract_mri_positive(rm, rm_absent)
    signals["emg_positive"] = _extract_emg_positive(eg, rm, data_absent)
    signals["fracture"] = _extract_fracture(eg, rm, data_absent)
    signals["surgery_performed"] = _extract_surgery_performed(eg, eg_absent)
    signals["injection_performed"] = _extract_injection_performed(eg, rm, data_absent)
    signals["hardware_implanted"] = _extract_hardware_implanted(eg, eg_absent)
    signals["total_visits"] = _extract_total_visits(rm, rm_absent)
    signals["treatment_duration_days"] = _extract_treatment_duration_days(rm, rm_absent)
    signals["gap_over_30_days"] = _extract_gap_over_30_days(eg, eg_absent)
    signals["compliance_rate"] = _extract_compliance_rate(eg, eg_absent)
    signals["similar_body_part_prior"] = _extract_similar_body_part_prior(eg, eg_absent)
    signals["documentation_overlap_score"] = _extract_documentation_overlap_score(eg, eg_absent)
    signals["future_surgery_recommended"] = _extract_future_surgery_recommended(eg, rm, data_absent)
    signals["impairment_rating_present"] = _extract_impairment_rating_present(eg, eg_absent)
    signals["documented_wage_loss"] = _extract_documented_wage_loss(eg, eg_absent)
    signals["lost_work_days"] = _extract_lost_work_days(eg, eg_absent)

    return signals


# ── Scoring ───────────────────────────────────────────────────────────────────

def _bool_val(signals: dict[str, SlmSignalAudit], name: str) -> bool:
    sig = signals.get(name)
    return sig is not None and sig.value is True


def _float_val(signals: dict[str, SlmSignalAudit], name: str) -> float | None:
    sig = signals.get(name)
    if sig is None or sig.value is None:
        return None
    try:
        return float(sig.value)
    except Exception:
        return None


def _score_domains(signals: dict[str, SlmSignalAudit]) -> dict[str, float]:
    # Liability signal values (tri-state)
    police_val = signals["police_report_support"].value if "police_report_support" in signals else None
    independent_val = signals["independent_witness"].value if "independent_witness" in signals else None
    comp_fault_val = _float_val(signals, "comparative_fault_risk")

    mri = 1 if _bool_val(signals, "mri_positive") else 0
    emg = 1 if _bool_val(signals, "emg_positive") else 0
    fracture = 1 if _bool_val(signals, "fracture") else 0
    surgery = 1 if _bool_val(signals, "surgery_performed") else 0
    injection = 1 if _bool_val(signals, "injection_performed") else 0
    hardware = 1 if _bool_val(signals, "hardware_implanted") else 0

    treatment_duration_val = _float_val(signals, "treatment_duration_days")
    gap_over_30 = _bool_val(signals, "gap_over_30_days")
    compliance_rate_val = _float_val(signals, "compliance_rate")
    similar_prior = _bool_val(signals, "similar_body_part_prior")
    doc_overlap_val = _float_val(signals, "documentation_overlap_score")
    future_surgery = _bool_val(signals, "future_surgery_recommended")
    impairment = _bool_val(signals, "impairment_rating_present")

    # A. Liability Strength
    # UNKNOWN signals contribute 0 — neither bonus nor penalty
    liability_strength = clamp01(
        0.5
        + (0.25 if police_val is True else 0)
        + (0.15 if independent_val is True else 0)
        - ((comp_fault_val * 0.5) if comp_fault_val is not None else 0)
    )

    # B. Damages Objectivity
    damages_objectivity = clamp01(
        0.30 * mri + 0.20 * emg + 0.40 * fracture
        + 0.50 * surgery + 0.25 * injection + 0.40 * hardware
    )

    # C. Escalation Signal
    escalation_signal = clamp01(
        0.2 + 0.3 * injection + 0.5 * surgery
        + (0.2 if treatment_duration_val is not None and treatment_duration_val > 120 else 0)
    )

    # D. Treatment Continuity
    treatment_continuity = clamp01(
        (compliance_rate_val if compliance_rate_val is not None else 0.0)
        - (0.25 if gap_over_30 else 0)
    )

    # E. Defense Risk Index (inverse leverage)
    defense_risk_index = clamp01(
        0.4 * (1 if similar_prior else 0)
        + (doc_overlap_val if doc_overlap_val is not None else 0) * 0.4
        + 0.3 * (1 if gap_over_30 else 0)
    )

    # F. Permanency Signal
    permanency_signal = clamp01(
        0.6 * (1 if future_surgery else 0)
        + 0.4 * (1 if impairment else 0)
    )

    # Composite SLI
    sli = clamp01(
        liability_strength * 0.25
        + damages_objectivity * 0.25
        + escalation_signal * 0.15
        + treatment_continuity * 0.10
        + permanency_signal * 0.15
        - defense_risk_index * 0.20
    )

    return {
        "sli": sli,
        "liability_strength": liability_strength,
        "damages_objectivity": damages_objectivity,
        "escalation_signal": escalation_signal,
        "treatment_continuity": treatment_continuity,
        "defense_risk_index": defense_risk_index,
        "permanency_signal": permanency_signal,
    }


def _map_posture(sli: float) -> str:
    if sli >= 0.75:
        return "PUSH_HIGH_ANCHOR"
    if sli >= 0.60:
        return "STRONG_STANDARD_DEMAND"
    if sli >= 0.45:
        return "BUILD_CASE"
    if sli >= 0.30:
        return "FIX_WEAKNESSES"
    return "HIGH_RISK_SETTLEMENT"


def _compute_confidence_score(signals: dict[str, SlmSignalAudit]) -> float:
    """Average provenance weight over non-UNKNOWN (non-None) signals only."""
    weights = [
        _CONF_WEIGHTS[sig.provenance.confidence]
        for sig in signals.values()
        if sig.value is not None
    ]
    return sum(weights) / len(weights) if weights else 0.0


# ── Public entry point ────────────────────────────────────────────────────────

def build_settlement_leverage_model(
    evidence_graph_payload: dict | None,
    renderer_manifest: dict | None,
) -> dict[str, Any]:
    """
    Compute Settlement Leverage Model v1.

    Parameters
    ----------
    evidence_graph_payload
        JSON-serialised EvidenceGraph (from ``evidence_graph.model_dump(mode="json")``)
        or None / empty dict when not available.
    renderer_manifest
        JSON-serialised RendererManifest (from ``renderer_manifest.model_dump(mode="json")``)
        or None / empty dict when not available.

    Returns
    -------
    dict
        Fields matching ``SettlementLeverageModel``, serialised to JSON-compatible types.
        Never raises — returns a valid dict even on internal error.
    """
    try:
        eg = evidence_graph_payload if isinstance(evidence_graph_payload, dict) else None
        rm = renderer_manifest if isinstance(renderer_manifest, dict) else None

        signals = _extract_all_signals(eg, rm)
        scores = _score_domains(signals)
        posture = _map_posture(scores["sli"])
        confidence = _compute_confidence_score(signals)

        # Round to 4 decimal places exactly once here — not in intermediate computation
        model = SettlementLeverageModel(
            schema_version="slm.v1",
            settlement_leverage_index=round(scores["sli"], 4),
            liability_strength=round(scores["liability_strength"], 4),
            damages_objectivity=round(scores["damages_objectivity"], 4),
            escalation_signal=round(scores["escalation_signal"], 4),
            treatment_continuity=round(scores["treatment_continuity"], 4),
            defense_risk_index=round(scores["defense_risk_index"], 4),
            permanency_signal=round(scores["permanency_signal"], 4),
            recommended_posture=posture,  # type: ignore[arg-type]
            confidence_score=round(confidence, 4),
            input_signals=signals,
        )
        return model.model_dump(mode="json")

    except Exception as exc:
        logger.exception(f"SLM build failed: {exc}")
        # Deterministic no-data fallback — matches the spec baseline
        return {
            "schema_version": "slm.v1",
            "settlement_leverage_index": 0.155,
            "liability_strength": 0.5,
            "damages_objectivity": 0.0,
            "escalation_signal": 0.2,
            "treatment_continuity": 0.0,
            "defense_risk_index": 0.0,
            "permanency_signal": 0.0,
            "recommended_posture": "HIGH_RISK_SETTLEMENT",
            "confidence_score": 0.0,
            "input_signals": {},
            "error": str(exc),
        }
