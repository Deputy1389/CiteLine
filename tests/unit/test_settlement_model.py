"""Unit tests for SettlementModelReport.v1 (settlement_model.py)."""
import pytest
from apps.worker.lib.settlement_model import build_settlement_model_report


def _slm(posture="BUILD_CASE", sli=0.45, **signal_overrides) -> dict:
    """Build a minimal SLM dict for testing."""
    signals = {
        "mri_positive": {"value": None, "provenance": {"source_type": "not_determinable", "confidence": "MED", "entered_by": "SYSTEM"}},
        "surgery_performed": {"value": None, "provenance": {"source_type": "not_determinable", "confidence": "MED", "entered_by": "SYSTEM"}},
        "injection_performed": {"value": None, "provenance": {"source_type": "not_determinable", "confidence": "MED", "entered_by": "SYSTEM"}},
    }
    for k, v in signal_overrides.items():
        signals[k] = {"value": v, "provenance": {"source_type": "event", "confidence": "HIGH", "entered_by": "SYSTEM"}}
    return {
        "schema_version": "slm.v1",
        "settlement_leverage_index": sli,
        "recommended_posture": posture,
        "input_signals": signals,
    }


def _dam(flags_triggered=0, flags=None) -> dict:
    return {
        "schema_version": "dam.v2",
        "flags_triggered": flags_triggered,
        "flags": flags or [],
    }


def _csi(score=5.0, labels=None) -> dict:
    return {
        "schema_version": "csi.v1",
        "case_severity_index": score,
        "component_labels": labels or {
            "duration": "60–180 days",
            "treatment_intensity": "ED + PT",
            "objective_finding": "Soft tissue / spasm documented",
        },
        "profile": "Moderate severity.",
    }


def test_smr_empty_inputs_no_error():
    result = build_settlement_model_report(None, None, None)
    assert result["schema_version"] == "smr.v1"
    assert isinstance(result["strengths"], list)
    assert isinstance(result["risk_factors"], list)
    assert isinstance(result["posture_text"], str)


def test_smr_posture_propagated():
    result = build_settlement_model_report(None, _dam(), _csi(), slm := _slm("PUSH_HIGH_ANCHOR", 0.8))
    # Use keyword to avoid name collision
    result2 = build_settlement_model_report(None, _dam(), _csi(), _slm("PUSH_HIGH_ANCHOR", 0.8))
    assert result2["recommended_posture"] == "PUSH_HIGH_ANCHOR"


def test_smr_csi_score_propagated():
    result = build_settlement_model_report(None, _dam(), _csi(7.3), _slm())
    assert result["case_severity_index"] == 7.3


def test_smr_flags_triggered_propagated():
    dam = _dam(flags_triggered=3, flags=[
        {"flag_id": "CARE_GAP_OVER_30_DAYS", "triggered": True, "severity": "HIGH", "label": "Gap in Care (>30 days)"},
        {"flag_id": "CONSERVATIVE_CARE_ONLY", "triggered": True, "severity": "MED", "label": "Conservative Care Only"},
        {"flag_id": "LOW_PT_VISITS", "triggered": True, "severity": "MED", "label": "Low PT Visits (<6)"},
    ])
    result = build_settlement_model_report(None, dam, _csi(), _slm())
    assert result["flags_triggered"] == 3
    assert len(result["risk_factors"]) == 3


def test_smr_strengths_from_slm_signals():
    slm = _slm(mri_positive=True, surgery_performed=True)
    result = build_settlement_model_report(None, _dam(), _csi(), slm)
    assert any("MRI" in s or "imaging" in s.lower() for s in result["strengths"])
    assert any("Surgical" in s or "surgery" in s.lower() for s in result["strengths"])


def test_smr_no_strengths_when_all_signals_false():
    slm = _slm(mri_positive=False, surgery_performed=False, injection_performed=False)
    result = build_settlement_model_report(None, _dam(), _csi(), slm)
    # Signals set to False explicitly should not appear as strengths
    # (only True signals contribute)
    assert len(result["strengths"]) == 0


def test_smr_posture_text_non_empty():
    for posture in ["PUSH_HIGH_ANCHOR", "STRONG_STANDARD_DEMAND", "BUILD_CASE", "FIX_WEAKNESSES", "HIGH_RISK_SETTLEMENT"]:
        result = build_settlement_model_report(None, _dam(), _csi(), _slm(posture))
        assert len(result["posture_text"]) > 20, f"Empty posture text for {posture}"


def test_smr_gap_note_in_build_case_posture():
    dam = _dam(flags_triggered=1, flags=[
        {
            "flag_id": "CARE_GAP_OVER_30_DAYS",
            "triggered": True,
            "severity": "HIGH",
            "label": "Gap in Care (>30 days)",
            "detail": "179-day gap detected.",
        }
    ])
    result = build_settlement_model_report(None, dam, _csi(), _slm("BUILD_CASE"))
    assert "179" in result["posture_text"] or "gap" in result["posture_text"].lower()


def test_smr_csi_score_appended_to_posture_text():
    result = build_settlement_model_report(None, _dam(), _csi(6.7), _slm("BUILD_CASE"))
    assert "6.7" in result["posture_text"]


def test_smr_never_raises_on_garbage():
    result = build_settlement_model_report("bad", [1, 2], None, {"x": 1})
    assert result["schema_version"] == "smr.v1"
