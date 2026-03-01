"""Unit tests for SettlementFeaturePack.v1 (settlement_features.py)."""
import pytest
from apps.worker.lib.settlement_features import build_settlement_feature_pack


def _eg(**events_kwargs) -> dict:
    return {"events": events_kwargs.get("events", []), "gaps": events_kwargs.get("gaps", [])}


def _rm(**kwargs) -> dict:
    return kwargs


def test_sfp_empty_inputs_returns_valid_pack():
    result = build_settlement_feature_pack(None, None)
    assert result["schema_version"] == "sfp.v1"
    assert result["has_surgery"] is False
    assert result["has_injection"] is False
    assert result["treatment_duration_days"] is None
    assert result["max_gap_days"] == 0


def test_sfp_surgery_detected():
    ev = {
        "event_type": "procedure",
        "facts": [{"text": "Patient underwent cervical fusion surgery."}],
    }
    result = build_settlement_feature_pack({"events": [ev], "gaps": []}, {})
    assert result["has_surgery"] is True


def test_sfp_injection_detected():
    ev = {
        "event_type": "procedure",
        "facts": [{"text": "Epidural steroid injection administered."}],
    }
    result = build_settlement_feature_pack({"events": [ev], "gaps": []}, {})
    assert result["has_injection"] is True


def test_sfp_gap_fields():
    gap = {"duration_days": 45, "gap_id": "abc123", "date_from": "2024-01-01", "date_to": "2024-02-15"}
    result = build_settlement_feature_pack({"events": [], "gaps": [gap]}, {})
    assert result["max_gap_days"] == 45
    assert result["gap_count_over_30"] == 1
    assert result["largest_gap"]["gap_id"] == "abc123"


def test_sfp_gap_under_30_not_counted():
    gap = {"duration_days": 20}
    result = build_settlement_feature_pack({"events": [], "gaps": [gap]}, {})
    assert result["gap_count_over_30"] == 0
    assert result["max_gap_days"] == 20


def test_sfp_prior_similar_injury_from_event():
    ev = {"event_type": "referenced_prior_event", "facts": []}
    result = build_settlement_feature_pack({"events": [ev], "gaps": []}, {})
    assert result["has_prior_similar_injury"] is True


def test_sfp_treatment_duration_computed():
    rm = {"pt_summary": {"total_encounters": 12, "date_start": "2024-01-01", "date_end": "2024-04-10"}}
    result = build_settlement_feature_pack({"events": [], "gaps": []}, rm)
    # Jan 1 → Apr 10 2024 = 100 days (2024 is a leap year; 31+29+31+9=100)
    from datetime import date
    assert result["treatment_duration_days"] == (date(2024, 4, 10) - date(2024, 1, 1)).days
    assert result["treatment_duration_days"] == 100


def test_sfp_pt_summary_total_encounters():
    rm = {"pt_summary": {"total_encounters": 24, "count_source": "structured"}}
    result = build_settlement_feature_pack({}, rm)
    assert result["pt_total_encounters"] == 24
    assert result["has_pt"] is True


def test_sfp_mri_positive_from_promoted_finding():
    rm = {
        "promoted_findings": [{
            "category": "imaging",
            "finding_polarity": "positive",
            "label": "MRI cervical spine — disc herniation",
            "citation_ids": ["cit001"],
        }]
    }
    result = build_settlement_feature_pack({}, rm)
    assert result["has_mri_positive"] is True
    assert result["has_imaging"] is True
    assert result["has_disc_herniation"] is True


def test_sfp_radiculopathy_detected_in_promoted_finding():
    rm = {
        "promoted_findings": [{"category": "diagnosis", "label": "Cervical radiculopathy C5-C6", "citation_ids": []}]
    }
    result = build_settlement_feature_pack({}, rm)
    assert result["has_radiculopathy"] is True
    assert result["has_neuro_deficit_keywords"] is True


def test_sfp_fracture_not_present():
    rm = {
        "promoted_findings": [{"category": "imaging", "finding_polarity": "positive", "label": "disc bulge", "citation_ids": []}]
    }
    result = build_settlement_feature_pack({}, rm)
    assert result["has_fracture"] is False


def test_sfp_days_to_first_treatment():
    ev = {"event_type": "ed_visit", "date": "2024-01-10", "facts": []}
    rm = {"doi": "2024-01-03"}
    result = build_settlement_feature_pack({"events": [ev], "gaps": []}, rm)
    assert result["days_to_first_treatment"] == 7
    assert result["doi"] == "2024-01-03"


def test_sfp_never_raises_on_garbage_input():
    result = build_settlement_feature_pack("not a dict", [1, 2, 3])
    assert result["schema_version"] == "sfp.v1"
