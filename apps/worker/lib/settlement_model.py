"""
Settlement Model Report v1 — combined settlement intelligence report.

Combines the Settlement Leverage Model, Defense Attack Map, and Case Severity Index
into a single attorney-facing summary with strengths, risk factors, and posture text.

Public API:
    build_settlement_model_report(
        feature_pack, dam, csi, settlement_leverage_model=None
    ) -> dict

Returns a SettlementModelReport.v1 dict. Never raises.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── SLM signal labels for strengths ──────────────────────────────────────────

_POSITIVE_SIGNAL_LABELS: dict[str, str] = {
    "mri_positive": "Positive MRI / imaging findings documented",
    "emg_positive": "EMG positive for nerve involvement",
    "fracture": "Fracture documented on imaging",
    "surgery_performed": "Surgical procedure performed",
    "injection_performed": "Injection / interventional procedure performed",
    "hardware_implanted": "Hardware implanted (surgical fixation)",
    "future_surgery_recommended": "Future surgery recommended by treating physician",
    "impairment_rating_present": "Permanent impairment rating documented",
    "documented_wage_loss": "Wage loss documented",
}

# ── Posture paragraph templates ───────────────────────────────────────────────

_POSTURE_TEMPLATES: dict[str, str] = {
    "PUSH_HIGH_ANCHOR": (
        "This case presents strong leverage for a high-anchor demand. Objective findings, "
        "documented escalation, and favorable treatment continuity support an aggressive "
        "opening position."
    ),
    "STRONG_STANDARD_DEMAND": (
        "This case supports a confident standard demand. Medical documentation is solid "
        "with documented objective findings and consistent treatment. Proceed with a "
        "well-supported demand package."
    ),
    "BUILD_CASE": (
        "This case has documented objective findings and a {intensity_label} treatment "
        "course. {gap_note}Recommended: strengthen medical narrative before demand "
        "submission to maximize settlement value."
    ),
    "FIX_WEAKNESSES": (
        "This case has compensable injuries but notable risk factors that need to be "
        "addressed. {gap_note}Focus on obtaining additional supporting documentation "
        "and addressing causation gaps before demand."
    ),
    "HIGH_RISK_SETTLEMENT": (
        "This case presents significant settlement risk. Defense has multiple attack "
        "vectors. {gap_note}Consider early mediation and realistic demand calibration "
        "based on documented injuries only."
    ),
}


def _gap_note(dam: dict | None) -> str:
    """Produce a brief gap note from the highest-severity triggered DAM flag."""
    if not isinstance(dam, dict):
        return ""
    for flag in (dam.get("flags") or []):
        if not isinstance(flag, dict):
            continue
        if flag.get("triggered") and flag.get("flag_id") == "CARE_GAP_OVER_30_DAYS":
            detail = flag.get("detail") or ""
            if detail:
                return f"Key risk: {detail} "
    return ""


def _build_strengths(slm: dict | None) -> list[str]:
    """Extract positive signals from SLM input_signals."""
    if not isinstance(slm, dict):
        return []
    strengths: list[str] = []
    input_signals = slm.get("input_signals") or {}
    for sig_name, label in _POSITIVE_SIGNAL_LABELS.items():
        sig = input_signals.get(sig_name)
        if not isinstance(sig, dict):
            continue
        val = sig.get("value")
        if val is True:
            strengths.append(label)
    return strengths


def _build_risk_factors(dam: dict | None) -> list[str]:
    """Extract brief risk labels from triggered DAM flags."""
    if not isinstance(dam, dict):
        return []
    risks: list[str] = []
    for flag in (dam.get("flags") or []):
        if not isinstance(flag, dict):
            continue
        if flag.get("triggered"):
            severity = flag.get("severity", "MED")
            label = flag.get("label", "")
            risks.append(f"{label} [{severity}]")
    return risks


def _build_posture_text(
    slm: dict | None,
    dam: dict | None,
    csi: dict | None,
) -> str:
    """Build a deterministic posture paragraph from posture label + case context."""
    posture = "BUILD_CASE"
    if isinstance(slm, dict):
        posture = slm.get("recommended_posture") or "BUILD_CASE"

    template = _POSTURE_TEMPLATES.get(posture, _POSTURE_TEMPLATES["BUILD_CASE"])

    # Enrich template placeholders
    intensity_label = "moderate"
    if isinstance(csi, dict):
        cl = csi.get("component_labels") or {}
        intensity_label = cl.get("treatment_intensity", "moderate").lower()

    gap_note = _gap_note(dam)
    try:
        text = template.format(intensity_label=intensity_label, gap_note=gap_note)
    except KeyError:
        text = template

    # Append CSI summary
    if isinstance(csi, dict):
        csi_val = csi.get("case_severity_index")
        if csi_val is not None:
            text += f" Case Severity Index: {csi_val}/10."

    return text


def build_settlement_model_report(
    feature_pack: dict | None,
    dam: dict | None,
    csi: dict | None,
    settlement_leverage_model: dict | None = None,
) -> dict[str, Any]:
    """
    Build the Settlement Model Report v1.

    Parameters
    ----------
    feature_pack
        SettlementFeaturePack.v1 dict or None.
    dam
        DefenseAttackMap.v2 dict or None.
    csi
        CSI.v1 dict or None.
    settlement_leverage_model
        Existing SLM v1 dict from evidence_graph.extensions or None.

    Returns
    -------
    dict
        SettlementModelReport.v1 schema. Never raises.
    """
    try:
        slm = settlement_leverage_model if isinstance(settlement_leverage_model, dict) else {}

        strengths = _build_strengths(slm)
        risk_factors = _build_risk_factors(dam)
        posture_text = _build_posture_text(slm, dam, csi)

        # Top-level scores for quick access
        sli = slm.get("settlement_leverage_index")
        posture = slm.get("recommended_posture") or "BUILD_CASE"
        csi_score = (csi or {}).get("case_severity_index")
        flags_triggered = (dam or {}).get("flags_triggered", 0)

        return {
            "schema_version": "smr.v1",
            "settlement_leverage_index": sli,
            "recommended_posture": posture,
            "case_severity_index": csi_score,
            "flags_triggered": flags_triggered,
            "strengths": strengths,
            "risk_factors": risk_factors,
            "posture_text": posture_text,
        }
    except Exception as exc:
        logger.exception(f"SettlementModelReport build failed: {exc}")
        return {
            "schema_version": "smr.v1",
            "settlement_leverage_index": None,
            "recommended_posture": "BUILD_CASE",
            "case_severity_index": None,
            "flags_triggered": 0,
            "strengths": [],
            "risk_factors": [],
            "posture_text": "Settlement intelligence unavailable.",
            "error": str(exc),
        }
