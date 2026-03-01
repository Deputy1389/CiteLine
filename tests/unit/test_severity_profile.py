from apps.worker.lib.severity_profile import build_severity_profile


def test_build_severity_profile_v1_shape_and_no_numeric_valuation_fields():
    csi = {
        "schema_version": "csi.v2",
        "band": "Injection-tier profile",
        "component_scores": {
            "objective": {"tier_key": "radiculopathy", "label": "Radiculopathy documented"},
            "intensity": {"tier_key": "injection_specialist", "label": "Injection / specialist intervention documented"},
            "duration": {"tier_key": "61_180", "label": "61-180 day treatment course"},
        },
        "risk_factors": ["prior_similar_injury", "care_gap_over_60_days"],
        "support": {
            "citation_ids": ["c2", "c1", "c2"],
            "page_refs": [{"source_document_id": "doc-1", "page_number": 11}],
        },
    }
    out = build_severity_profile(csi)
    assert out["schema_version"] == "severity_profile.v1"
    assert out["export_intent"] == "mediation"
    assert out["band"] == "HIGH"
    assert "base_csi" not in out
    assert "risk_adjusted_csi" not in out
    assert "score_0_100" not in out
    assert out["support"]["citation_ids"] == ["c1", "c2"]
    assert len(out["severity_drivers"]) >= 3
    assert len(out["anticipated_defense_arguments"]) == 2


def test_build_severity_profile_deterministic():
    csi = {
        "schema_version": "csi.v2",
        "band": "Moderate soft tissue with objective support",
        "component_scores": {
            "objective": {"tier_key": "disc_displacement", "label": "Disc pathology documented"},
            "intensity": {"tier_key": "ed_imaging_pt", "label": "ED + imaging + PT course documented"},
            "duration": {"tier_key": "15_60", "label": "15-60 day treatment course"},
        },
        "risk_factors": ["delayed_first_care_over_14_days"],
        "support": {"citation_ids": ["c9", "c3"], "page_refs": []},
    }
    a = build_severity_profile(csi)
    b = build_severity_profile(csi)
    assert a == b

