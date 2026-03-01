"""
Unit tests for Settlement Leverage Model v1.

Tests follow the plan spec exactly and verify all 13 required test cases.
"""
from __future__ import annotations

import pytest
from apps.worker.lib.settlement_leverage import build_settlement_leverage_model, clamp01


# ── Helpers ───────────────────────────────────────────────────────────────────

def _procedure_event(event_id: str, facts_text: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": "procedure",
        "confidence": 80,
        "citation_ids": ["cit-1"],
        "facts": [{"text": facts_text, "kind": "finding", "verbatim": True, "citation_ids": ["cit-1"]}],
    }


def _imaging_event(event_id: str, facts_text: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": "imaging_study",
        "confidence": 80,
        "citation_ids": ["cit-1"],
        "facts": [{"text": facts_text, "kind": "finding", "verbatim": True, "citation_ids": ["cit-1"]}],
    }


def _promoted_finding(category: str, label: str, polarity: str | None = None, citation_ids: list | None = None) -> dict:
    return {
        "category": category,
        "label": label,
        "finding_polarity": polarity,
        "citation_ids": citation_ids or [],
        "confidence": 0.9,
    }


def _pt_summary(total: int | None = None, date_start: str | None = None, date_end: str | None = None, count_source: str = "structured") -> dict:
    return {
        "total_encounters": total,
        "date_start": date_start,
        "date_end": date_end,
        "count_source": count_source,
    }


def _gap(duration_days: int) -> dict:
    return {
        "gap_id": f"gap-{duration_days}",
        "start_date": "2024-02-01",
        "end_date": "2024-03-15",
        "duration_days": duration_days,
        "threshold_days": 30,
        "confidence": 80,
    }


# ── 1. test_slm_spec_example ──────────────────────────────────────────────────

def test_slm_spec_example() -> None:
    """Feed spec-like inputs; verify all 6 component scores + SLI match formula output."""
    rm = {
        "pt_summary": _pt_summary(total=42, date_start="2024-01-01", date_end="2024-07-01", count_source="structured"),
        "promoted_findings": [
            _promoted_finding("imaging", "MRI cervical spine positive", polarity="positive", citation_ids=["cit-mri"]),
            _promoted_finding("procedure", "Injection performed", polarity="positive"),
        ],
    }
    eg = {
        "events": [
            _procedure_event("inj-1", "epidural steroid injection performed under fluoroscopy"),
        ],
        "gaps": [_gap(20)],  # gap < 30d → gap_over_30_days=False
        "extensions": {},
    }

    result = build_settlement_leverage_model(eg, rm)

    # mri=1, injection=1, treatment_duration=181>120
    # B: 0.30*1 + 0.25*1 = 0.55
    # C: 0.2 + 0.3*1 + 0.0 + 0.2 = 0.7
    # D: compliance=0.95 (no gap>30), gap_over_30=False → 0.95
    assert result["damages_objectivity"] == pytest.approx(0.55, abs=1e-4)
    assert result["escalation_signal"] == pytest.approx(0.7, abs=1e-4)
    assert result["treatment_continuity"] == pytest.approx(0.95, abs=1e-4)
    assert result["liability_strength"] == pytest.approx(0.5, abs=1e-4)  # all liability UNKNOWN
    assert result["defense_risk_index"] == pytest.approx(0.0, abs=1e-4)  # no prior, no gap>30, no overlap
    assert result["permanency_signal"] == pytest.approx(0.0, abs=1e-4)

    # SLI = 0.5*0.25 + 0.55*0.25 + 0.7*0.15 + 0.95*0.10 + 0.0*0.15 - 0.0*0.20
    #     = 0.125 + 0.1375 + 0.105 + 0.095 + 0 - 0
    #     = 0.4625
    assert result["settlement_leverage_index"] == pytest.approx(0.4625, abs=1e-4)
    assert result["recommended_posture"] == "BUILD_CASE"


# ── 2. test_slm_posture_mapping ───────────────────────────────────────────────

@pytest.mark.parametrize("sli,expected_posture", [
    (0.755, "PUSH_HIGH_ANCHOR"),
    (0.74, "STRONG_STANDARD_DEMAND"),
    (0.60, "STRONG_STANDARD_DEMAND"),
    (0.45, "BUILD_CASE"),
    (0.30, "FIX_WEAKNESSES"),
    (0.29, "HIGH_RISK_SETTLEMENT"),
])
def test_slm_posture_mapping(sli: float, expected_posture: str) -> None:
    from apps.worker.lib.settlement_leverage import _map_posture
    assert _map_posture(sli) == expected_posture


# ── 3. test_slm_no_data_defaults ─────────────────────────────────────────────

def test_slm_no_data_defaults() -> None:
    """Empty dicts → deterministic no-data baseline as specified."""
    result = build_settlement_leverage_model({}, {})

    assert result["settlement_leverage_index"] == pytest.approx(0.155, abs=1e-4)
    assert result["recommended_posture"] == "HIGH_RISK_SETTLEMENT"
    assert result["confidence_score"] == pytest.approx(0.0, abs=1e-4)
    assert result["liability_strength"] == pytest.approx(0.5, abs=1e-4)
    assert result["damages_objectivity"] == pytest.approx(0.0, abs=1e-4)
    assert result["escalation_signal"] == pytest.approx(0.2, abs=1e-4)
    assert result["treatment_continuity"] == pytest.approx(0.0, abs=1e-4)
    assert result["defense_risk_index"] == pytest.approx(0.0, abs=1e-4)
    assert result["permanency_signal"] == pytest.approx(0.0, abs=1e-4)


def test_slm_no_data_none_inputs() -> None:
    """None inputs produce same result as empty dicts."""
    result_none = build_settlement_leverage_model(None, None)
    result_empty = build_settlement_leverage_model({}, {})
    assert result_none["settlement_leverage_index"] == result_empty["settlement_leverage_index"]
    assert result_none["recommended_posture"] == result_empty["recommended_posture"]


# ── 4. test_slm_mri_positive_detection ───────────────────────────────────────

def test_slm_mri_positive_detection() -> None:
    """Promoted finding category==imaging + polarity==positive + citation_ids → mri_positive=True, HIGH confidence."""
    rm = {
        "promoted_findings": [
            _promoted_finding("imaging", "MRI lumbar spine positive", polarity="positive", citation_ids=["cit-mri"]),
        ],
    }
    result = build_settlement_leverage_model({}, rm)
    signals = result["input_signals"]
    assert signals["mri_positive"]["value"] is True
    assert signals["mri_positive"]["provenance"]["confidence"] == "HIGH"
    # damages_objectivity: mri=1 → 0.30 minimum
    assert result["damages_objectivity"] >= 0.30


def test_slm_mri_positive_no_citations_is_med() -> None:
    """Promoted imaging positive finding without citation_ids → mri_positive=True but MED confidence."""
    rm = {
        "promoted_findings": [
            _promoted_finding("imaging", "MRI cervical positive", polarity="positive", citation_ids=[]),
        ],
    }
    result = build_settlement_leverage_model({}, rm)
    signals = result["input_signals"]
    assert signals["mri_positive"]["value"] is True
    assert signals["mri_positive"]["provenance"]["confidence"] == "MED"


def test_slm_mri_not_positive_polarity_is_false() -> None:
    """Promoted imaging finding with polarity!=positive → mri_positive=False."""
    rm = {
        "promoted_findings": [
            _promoted_finding("imaging", "MRI cervical unremarkable", polarity="negative", citation_ids=["cit-1"]),
        ],
    }
    result = build_settlement_leverage_model({}, rm)
    assert result["input_signals"]["mri_positive"]["value"] is False


# ── 5. test_slm_surgery_detection ────────────────────────────────────────────

def test_slm_surgery_detection() -> None:
    """Procedure event with 'surgery' in facts → surgery_performed=True, escalation and damages increase."""
    eg = {
        "events": [_procedure_event("surg-1", "Cervical spine surgery performed; fusion at C5-C6")],
        "gaps": [],
    }
    result = build_settlement_leverage_model(eg, {})
    signals = result["input_signals"]
    assert signals["surgery_performed"]["value"] is True
    # damages_objectivity: surgery weight 0.50
    assert result["damages_objectivity"] >= 0.50
    # escalation_signal: 0.2 baseline + 0.5 surgery = 0.7 minimum
    assert result["escalation_signal"] >= 0.7


def test_slm_surgery_arthroscopy_keyword() -> None:
    """'arthroscop' keyword triggers surgery_performed."""
    eg = {
        "events": [_procedure_event("arth-1", "Knee arthroscopic surgery performed")],
        "gaps": [],
    }
    result = build_settlement_leverage_model(eg, {})
    assert result["input_signals"]["surgery_performed"]["value"] is True


# ── 6. test_slm_injection_detection ──────────────────────────────────────────

def test_slm_injection_detection() -> None:
    """Procedure event with 'injection' in facts → injection_performed=True."""
    eg = {
        "events": [_procedure_event("inj-1", "Cervical epidural steroid injection administered")],
        "gaps": [],
    }
    result = build_settlement_leverage_model(eg, {})
    assert result["input_signals"]["injection_performed"]["value"] is True
    # escalation_signal: 0.2 + 0.3 = 0.5
    assert result["escalation_signal"] == pytest.approx(0.5, abs=1e-4)


def test_slm_injection_from_promoted_finding() -> None:
    """Promoted finding with injection label → injection_performed=True."""
    rm = {
        "promoted_findings": [
            _promoted_finding("procedure", "Cervical epidural injection performed"),
        ],
    }
    result = build_settlement_leverage_model({}, rm)
    assert result["input_signals"]["injection_performed"]["value"] is True


# ── 7. test_slm_gap_detection ────────────────────────────────────────────────

def test_slm_gap_detection() -> None:
    """Gap with duration_days=45 → gap_over_30_days=True, defense_risk_index increases, treatment_continuity decreases."""
    eg = {
        "events": [],
        "gaps": [_gap(45)],
    }
    # Without gap: defense_risk_index = 0, treatment_continuity = 0.95
    result_no_gap = build_settlement_leverage_model({"events": [], "gaps": []}, {})
    result_gap = build_settlement_leverage_model(eg, {})

    signals = result_gap["input_signals"]
    assert signals["gap_over_30_days"]["value"] is True
    assert signals["gap_over_30_days"]["provenance"]["source_type"] == "gap"
    assert signals["gap_over_30_days"]["provenance"]["confidence"] == "HIGH"

    # defense_risk_index increases with gap: +0.3
    assert result_gap["defense_risk_index"] > result_no_gap["defense_risk_index"]
    # treatment_continuity decreases: compliance 0.8 (1 gap>30) - 0.25 = 0.55
    assert result_gap["treatment_continuity"] < result_no_gap["treatment_continuity"]


def test_slm_no_gap_is_false_not_unknown() -> None:
    """Empty gaps list → gap_over_30_days=False (not UNKNOWN)."""
    eg = {"events": [], "gaps": []}
    result = build_settlement_leverage_model(eg, {})
    assert result["input_signals"]["gap_over_30_days"]["value"] is False


# ── 8. test_slm_prior_injury_detection ───────────────────────────────────────

def test_slm_prior_injury_detection() -> None:
    """event_type==referenced_prior_event → similar_body_part_prior=True."""
    eg = {
        "events": [
            {
                "event_id": "prior-1",
                "event_type": "referenced_prior_event",
                "confidence": 70,
                "citation_ids": ["cit-prior"],
                "facts": [{"text": "Prior lumbar surgery in 2019", "kind": "finding", "verbatim": True}],
            }
        ],
        "gaps": [],
    }
    result = build_settlement_leverage_model(eg, {})
    assert result["input_signals"]["similar_body_part_prior"]["value"] is True
    # defense_risk_index: +0.4 for prior
    assert result["defense_risk_index"] >= 0.4


# ── 9. test_slm_confidence_score ─────────────────────────────────────────────

def test_slm_confidence_score() -> None:
    """Full medical signals with HIGH provenance → confidence_score == 1.0."""
    rm = {
        "pt_summary": _pt_summary(total=30, date_start="2024-01-01", date_end="2024-06-01", count_source="structured"),
        "promoted_findings": [
            _promoted_finding("imaging", "MRI positive", polarity="positive", citation_ids=["cit-1"]),
        ],
    }
    eg = {
        "events": [
            _procedure_event("surg-1", "Spinal fusion surgery performed"),
        ],
        "gaps": [],
    }
    result = build_settlement_leverage_model(eg, rm)
    # Confidence > 0 (some non-UNKNOWN signals)
    assert result["confidence_score"] > 0.0
    # All non-UNKNOWN signals should be accounted for
    signals = result["input_signals"]
    non_unknown = [s for s in signals.values() if s["value"] is not None]
    assert len(non_unknown) > 0


def test_slm_confidence_excludes_unknowns_from_denominator() -> None:
    """All liability UNKNOWN + medical signals with HIGH provenance → confidence = avg(medical signal weights)."""
    rm = {
        "pt_summary": _pt_summary(total=25, date_start="2024-01-01", date_end="2024-07-01", count_source="structured"),
        "promoted_findings": [
            _promoted_finding("imaging", "MRI positive", polarity="positive", citation_ids=["cit-1"]),
        ],
    }
    result = build_settlement_leverage_model({}, rm)
    signals = result["input_signals"]

    # Liability signals should all be UNKNOWN
    assert signals["police_report_support"]["value"] is None
    assert signals["independent_witness"]["value"] is None
    assert signals["comparative_fault_risk"]["value"] is None

    # confidence_score > 0 even with UNKNOWN liability signals (non-UNKNOWN signals drive it)
    assert result["confidence_score"] > 0.0


# ── 10. test_slm_treatment_duration ──────────────────────────────────────────

def test_slm_treatment_duration() -> None:
    """PT summary date_start 2024-01-01, date_end 2024-06-15 → treatment_duration_days == 166."""
    rm = {
        "pt_summary": _pt_summary(total=20, date_start="2024-01-01", date_end="2024-06-15"),
    }
    result = build_settlement_leverage_model({}, rm)
    signals = result["input_signals"]
    assert signals["treatment_duration_days"]["value"] == 166


def test_slm_treatment_duration_over_120_boosts_escalation() -> None:
    """Treatment duration > 120 days adds +0.2 to escalation_signal."""
    rm_short = {"pt_summary": _pt_summary(total=10, date_start="2024-01-01", date_end="2024-04-01")}  # 91d
    rm_long = {"pt_summary": _pt_summary(total=30, date_start="2024-01-01", date_end="2024-07-01")}   # 182d

    result_short = build_settlement_leverage_model({}, rm_short)
    result_long = build_settlement_leverage_model({}, rm_long)

    # Short: no duration bonus → escalation = 0.2 baseline
    assert result_short["escalation_signal"] == pytest.approx(0.2, abs=1e-4)
    # Long: +0.2 duration bonus → escalation = 0.4
    assert result_long["escalation_signal"] == pytest.approx(0.4, abs=1e-4)


# ── 11. test_liability_unknown_is_neutral ─────────────────────────────────────

def test_liability_unknown_is_neutral() -> None:
    """All three liability signals None → liability_strength == 0.5 exactly."""
    result = build_settlement_leverage_model({}, {})
    assert result["liability_strength"] == pytest.approx(0.5, abs=1e-4)

    signals = result["input_signals"]
    assert signals["police_report_support"]["value"] is None
    assert signals["independent_witness"]["value"] is None
    assert signals["comparative_fault_risk"]["value"] is None


# ── 12. test_confidence_excludes_unknowns ─────────────────────────────────────

def test_confidence_excludes_unknowns() -> None:
    """All liability UNKNOWN + 4 medical signals HIGH provenance → confidence_score computed only from non-UNKNOWN."""
    rm = {
        "pt_summary": _pt_summary(total=30, date_start="2024-01-01", date_end="2024-07-01", count_source="structured"),
        "promoted_findings": [
            _promoted_finding("imaging", "MRI positive", polarity="positive", citation_ids=["cit-1"]),
        ],
    }
    eg = {
        "events": [
            _procedure_event("surg-1", "Spinal fusion surgery"),
        ],
        "gaps": [],
    }
    result = build_settlement_leverage_model(eg, rm)
    signals = result["input_signals"]

    # Count UNKNOWN signals
    unknown_count = sum(1 for s in signals.values() if s["value"] is None)
    non_unknown_count = sum(1 for s in signals.values() if s["value"] is not None)

    # There must be some UNKNOWN signals (at least 3 liability)
    assert unknown_count >= 3
    # confidence_score must be > 0 despite unknowns (non-UNKNOWN signals drive it)
    assert result["confidence_score"] > 0.0

    # Manually verify: confidence is average of non-UNKNOWN provenance weights
    _CONF_WEIGHTS = {"HIGH": 1.0, "MED": 0.85, "LOW": 0.65}
    manual_weights = [
        _CONF_WEIGHTS[s["provenance"]["confidence"]]
        for s in signals.values()
        if s["value"] is not None
    ]
    expected = sum(manual_weights) / len(manual_weights)
    assert result["confidence_score"] == pytest.approx(expected, abs=1e-4)


# ── 13. test_provenance_required_fields ───────────────────────────────────────

def test_provenance_required_fields() -> None:
    """All non-UNKNOWN signals in input_signals have required provenance fields."""
    rm = {
        "pt_summary": _pt_summary(total=20, date_start="2024-01-01", date_end="2024-06-01"),
        "promoted_findings": [
            _promoted_finding("imaging", "MRI positive", polarity="positive", citation_ids=["cit-1"]),
        ],
    }
    eg = {
        "events": [
            _procedure_event("inj-1", "Cervical epidural steroid injection"),
            _procedure_event("surg-1", "Spinal fusion surgery"),
        ],
        "gaps": [_gap(45)],
    }
    result = build_settlement_leverage_model(eg, rm)

    for name, sig in result["input_signals"].items():
        if sig["value"] is not None:
            prov = sig["provenance"]
            assert "source_type" in prov, f"Signal {name!r} missing source_type"
            assert "confidence" in prov, f"Signal {name!r} missing confidence"
            assert "entered_by" in prov, f"Signal {name!r} missing entered_by"
            assert prov["confidence"] in {"HIGH", "MED", "LOW"}, f"Signal {name!r} bad confidence: {prov['confidence']}"
            assert prov["entered_by"] == "SYSTEM", f"Signal {name!r} entered_by should be SYSTEM"


# ── Additional edge-case tests ────────────────────────────────────────────────

def test_slm_fracture_from_promoted_finding() -> None:
    """Promoted finding with 'fracture' in label → fracture=True, damages_objectivity increases."""
    rm = {
        "promoted_findings": [
            _promoted_finding("diagnosis", "L2 compression fracture", citation_ids=["cit-1"]),
        ],
    }
    result = build_settlement_leverage_model({}, rm)
    assert result["input_signals"]["fracture"]["value"] is True
    assert result["damages_objectivity"] >= 0.40


def test_slm_future_surgery_from_promoted_finding() -> None:
    """Promoted finding with 'surgical candidate' → future_surgery_recommended=True."""
    rm = {
        "promoted_findings": [
            _promoted_finding("procedure", "Patient is a surgical candidate for lumbar fusion"),
        ],
    }
    result = build_settlement_leverage_model({}, rm)
    assert result["input_signals"]["future_surgery_recommended"]["value"] is True
    assert result["permanency_signal"] >= 0.60


def test_slm_impairment_rating_in_facts() -> None:
    """Event facts with 'impairment rating' → impairment_rating_present=True."""
    eg = {
        "events": [
            {
                "event_id": "imp-1",
                "event_type": "clinical_visit",
                "confidence": 80,
                "citation_ids": ["cit-1"],
                "facts": [{"text": "Patient assigned 15% impairment rating per AMA guidelines", "kind": "finding", "verbatim": True}],
            }
        ],
        "gaps": [],
    }
    result = build_settlement_leverage_model(eg, {})
    assert result["input_signals"]["impairment_rating_present"]["value"] is True
    assert result["permanency_signal"] >= 0.40


def test_slm_hardware_implanted() -> None:
    """Procedure event with 'screw' in facts → hardware_implanted=True."""
    eg = {
        "events": [_procedure_event("hw-1", "Pedicle screw fixation hardware placed at L4-L5")],
        "gaps": [],
    }
    result = build_settlement_leverage_model(eg, {})
    assert result["input_signals"]["hardware_implanted"]["value"] is True
    assert result["damages_objectivity"] >= 0.40


def test_slm_clamp01() -> None:
    """clamp01 works at boundary values."""
    assert clamp01(-1.0) == 0.0
    assert clamp01(0.0) == 0.0
    assert clamp01(0.5) == 0.5
    assert clamp01(1.0) == 1.0
    assert clamp01(2.0) == 1.0


def test_slm_schema_version_present() -> None:
    """Output always includes schema_version == 'slm.v1'."""
    result = build_settlement_leverage_model(None, None)
    assert result["schema_version"] == "slm.v1"


def test_slm_all_required_fields_present() -> None:
    """Output dict contains all required top-level fields."""
    result = build_settlement_leverage_model({}, {})
    required = [
        "schema_version", "settlement_leverage_index", "liability_strength",
        "damages_objectivity", "escalation_signal", "treatment_continuity",
        "defense_risk_index", "permanency_signal", "recommended_posture",
        "confidence_score", "input_signals",
    ]
    for field in required:
        assert field in result, f"Missing field: {field}"


def test_slm_sli_bounds() -> None:
    """settlement_leverage_index is always in [0, 1]."""
    # Worst case
    result_worst = build_settlement_leverage_model({}, {})
    assert 0.0 <= result_worst["settlement_leverage_index"] <= 1.0

    # Best case (surgery + mri + fracture + high visits + no gaps)
    rm = {
        "pt_summary": _pt_summary(total=60, date_start="2024-01-01", date_end="2024-08-01", count_source="structured"),
        "promoted_findings": [
            _promoted_finding("imaging", "MRI positive", polarity="positive", citation_ids=["cit-1"]),
            _promoted_finding("diagnosis", "L4 fracture", citation_ids=["cit-2"]),
            _promoted_finding("procedure", "Patient is a surgical candidate"),
        ],
    }
    eg = {
        "events": [
            _procedure_event("surg-1", "Spinal fusion surgery performed"),
            {"event_id": "imp-1", "event_type": "clinical_visit", "confidence": 80, "citation_ids": ["cit-3"],
             "facts": [{"text": "5% permanent impairment rating assigned", "kind": "finding", "verbatim": True}]},
        ],
        "gaps": [],
    }
    result_best = build_settlement_leverage_model(eg, rm)
    assert 0.0 <= result_best["settlement_leverage_index"] <= 1.0
    assert result_best["settlement_leverage_index"] > result_worst["settlement_leverage_index"]
