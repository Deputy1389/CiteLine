"""Unit tests for DefenseAttackMap.v2 (defense_attack_map.py)."""
import pytest
from apps.worker.lib.defense_attack_map import build_defense_attack_map


def _make_fp(**kwargs) -> dict:
    """Build a minimal feature pack for DAM testing."""
    base = {
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
    base.update(kwargs)
    return base


def test_dam_no_data_returns_valid_empty():
    result = build_defense_attack_map(None, None)
    assert result["schema_version"] == "dam.v2"
    assert result["flags_checked"] == 8
    assert isinstance(result["flags"], list)
    assert len(result["flags"]) == 8
    assert all(f["triggered"] is False for f in result["flags"])


def test_dam_care_gap_fires_over_30_days():
    fp = _make_fp(
        gaps=[{"duration_days": 45, "gap_id": "g1", "date_from": "2024-01-01", "date_to": "2024-02-15"}],
        max_gap_days=45,
        gap_count_over_30=1,
    )
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "CARE_GAP_OVER_30_DAYS")
    assert flag["triggered"] is True
    assert flag["severity"] == "HIGH"
    assert "45" in flag["detail"]
    assert result["flags_triggered"] >= 1


def test_dam_care_gap_does_not_fire_under_30():
    fp = _make_fp(
        gaps=[{"duration_days": 20}],
        max_gap_days=20,
        gap_count_over_30=0,
    )
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "CARE_GAP_OVER_30_DAYS")
    assert flag["triggered"] is False


def test_dam_conservative_care_fires_no_surgery_no_injection():
    # Care present but only conservative (ED + PT, no surgery/injection)
    fp = _make_fp(has_surgery=False, has_injection=False, has_ed_visit=True, has_pt=True)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "CONSERVATIVE_CARE_ONLY")
    assert flag["triggered"] is True


def test_dam_surgery_suppresses_conservative_flag():
    fp = _make_fp(has_surgery=True, has_injection=False, has_ed_visit=True)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "CONSERVATIVE_CARE_ONLY")
    assert flag["triggered"] is False


def test_dam_injection_suppresses_conservative_flag():
    fp = _make_fp(has_surgery=False, has_injection=True, has_ed_visit=True)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "CONSERVATIVE_CARE_ONLY")
    assert flag["triggered"] is False


def test_dam_prior_injury_fires():
    fp = _make_fp(has_prior_similar_injury=True)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "PRIOR_SIMILAR_INJURY")
    assert flag["triggered"] is True
    assert flag["severity"] == "HIGH"


def test_dam_imaging_no_fracture_fires():
    imaging_pf = [{"category": "imaging", "finding_polarity": "positive", "label": "disc bulge", "citation_ids": ["c1"]}]
    fp = _make_fp(has_imaging=True, has_fracture=False, imaging_promoted_findings=imaging_pf)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "IMAGING_NO_FRACTURE")
    assert flag["triggered"] is True


def test_dam_imaging_no_fracture_does_not_fire_when_fracture_present():
    imaging_pf = [{"category": "imaging", "label": "fracture L3", "citation_ids": []}]
    fp = _make_fp(has_imaging=True, has_fracture=True, imaging_promoted_findings=imaging_pf)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "IMAGING_NO_FRACTURE")
    assert flag["triggered"] is False


def test_dam_low_pt_visits_fires():
    fp = _make_fp(pt_total_encounters=3)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "LOW_PT_VISITS")
    assert flag["triggered"] is True
    assert "3" in flag["detail"]


def test_dam_low_pt_visits_does_not_fire_at_threshold():
    fp = _make_fp(pt_total_encounters=6)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "LOW_PT_VISITS")
    assert flag["triggered"] is False


def test_dam_delayed_treatment_fires():
    fp = _make_fp(days_to_first_treatment=10, doi="2024-01-01", first_event_date="2024-01-11")
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "DELAYED_FIRST_TREATMENT")
    assert flag["triggered"] is True
    assert "10" in flag["detail"]


def test_dam_delayed_treatment_does_not_fire_at_7_days():
    fp = _make_fp(days_to_first_treatment=7)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "DELAYED_FIRST_TREATMENT")
    assert flag["triggered"] is False


def test_dam_no_neuro_deficit_fires():
    # Care documented (imaging present) but no neuro deficit found
    fp = _make_fp(has_emg_positive=False, has_neuro_deficit_keywords=False, has_imaging=True)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "NO_OBJECTIVE_NEURO_DEFICIT")
    assert flag["triggered"] is True


def test_dam_neuro_deficit_keywords_suppress_flag():
    fp = _make_fp(has_neuro_deficit_keywords=True)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "NO_OBJECTIVE_NEURO_DEFICIT")
    assert flag["triggered"] is False


def test_dam_defense_argument_and_counter_present_for_triggered():
    fp = _make_fp(
        gaps=[{"duration_days": 50, "gap_id": "g1"}],
        max_gap_days=50,
        gap_count_over_30=1,
    )
    result = build_defense_attack_map(None, None, feature_pack=fp)
    for flag in result["flags"]:
        if flag["triggered"]:
            assert len(flag["defense_argument"]) > 10, f"Empty defense_argument for {flag['flag_id']}"
            assert len(flag["plaintiff_counter"]) > 10, f"Empty plaintiff_counter for {flag['flag_id']}"


def test_dam_care_gap_citation_ids_from_gap():
    fp = _make_fp(
        gaps=[{"duration_days": 179, "gap_id": "gap-uuid-001"}],
        max_gap_days=179,
        gap_count_over_30=1,
    )
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "CARE_GAP_OVER_30_DAYS")
    assert flag["triggered"] is True
    assert "gap-uuid-001" in flag["citation_ids"]


def test_dam_flags_triggered_count_matches():
    fp = _make_fp(
        gaps=[{"duration_days": 90}],
        max_gap_days=90,
        gap_count_over_30=1,
        has_prior_similar_injury=True,
    )
    result = build_defense_attack_map(None, None, feature_pack=fp)
    expected_count = sum(1 for f in result["flags"] if f["triggered"])
    assert result["flags_triggered"] == expected_count


def test_dam_short_treatment_duration_fires():
    fp = _make_fp(treatment_duration_days=14)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "SHORT_TREATMENT_DURATION")
    assert flag["triggered"] is True


def test_dam_short_treatment_duration_does_not_fire_at_30():
    fp = _make_fp(treatment_duration_days=30)
    result = build_defense_attack_map(None, None, feature_pack=fp)
    flag = next(f for f in result["flags"] if f["flag_id"] == "SHORT_TREATMENT_DURATION")
    assert flag["triggered"] is False
