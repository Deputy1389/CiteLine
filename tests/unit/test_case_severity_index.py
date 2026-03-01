"""Unit tests for Case Severity Index v2."""

from apps.worker.lib.case_severity_index import build_case_severity_index


def _rm(**overrides):
    base = {
        "pt_summary": {
            "date_start": None,
            "date_end": None,
            "citation_ids": [],
            "total_encounters": None,
        },
        "promoted_findings": [],
        "bucket_evidence": {"ed": {"citation_ids": []}},
    }
    base.update(overrides)
    return base


def _fp(**overrides):
    base = {
        "has_surgery": False,
        "has_injection": False,
        "has_specialist": False,
        "has_ed_visit": False,
        "has_imaging": False,
        "has_pt": False,
        "has_radiculopathy": False,
        "has_disc_herniation": False,
        "has_soft_tissue": False,
        "max_gap_days": 0,
        "has_prior_similar_injury": False,
    }
    base.update(overrides)
    return base


def _eg(**overrides):
    base = {"extensions": {}, "citations": []}
    base.update(overrides)
    return base


def test_csi_v2_schema_shape_and_compat_fields():
    out = build_case_severity_index(_eg(), _rm(), _fp())
    assert out["schema_version"] == "csi.v2"
    assert "base_csi" in out and "risk_adjusted_csi" in out
    assert "component_scores" in out and "selected_tiers" in out
    assert "support" in out and "citation_ids" in out["support"]
    # compatibility
    assert "case_severity_index" in out
    assert "duration_score" in out
    assert "component_labels" in out


def test_duration_bucket_edges_and_invalid_dates_default_to_3():
    out = build_case_severity_index(_eg(), _rm(pt_summary={"date_start": "2025-01-01", "date_end": "2025-01-10", "citation_ids": []}), _fp())
    assert out["component_scores"]["duration"]["score"] == 1

    out = build_case_severity_index(_eg(), _rm(pt_summary={"date_start": "2025-01-01", "date_end": "2025-03-01", "citation_ids": []}), _fp())
    assert out["component_scores"]["duration"]["score"] == 3

    out = build_case_severity_index(_eg(), _rm(pt_summary={"date_start": "2025-01-01", "date_end": "2025-06-01", "citation_ids": []}), _fp())
    assert out["component_scores"]["duration"]["score"] == 6

    out = build_case_severity_index(_eg(), _rm(pt_summary={"date_start": "2025-01-01", "date_end": "2025-12-31", "citation_ids": []}), _fp())
    assert out["component_scores"]["duration"]["score"] == 9

    out = build_case_severity_index(_eg(), _rm(pt_summary={"date_start": "2025-06-01", "date_end": "2025-01-01", "citation_ids": []}), _fp())
    assert out["component_scores"]["duration"]["score"] == 3


def test_intensity_hierarchy_highest_tier_wins():
    out = build_case_severity_index(_eg(), _rm(), _fp(has_ed_visit=True, has_imaging=True, has_pt=True))
    assert out["component_scores"]["intensity"]["tier_key"] == "ed_imaging_pt"

    out = build_case_severity_index(_eg(), _rm(), _fp(has_ed_visit=True, has_imaging=True, has_pt=True, has_injection=True))
    assert out["component_scores"]["intensity"]["tier_key"] == "injection_specialist"

    out = build_case_severity_index(_eg(), _rm(), _fp(has_surgery=True, has_injection=True, has_ed_visit=True))
    assert out["component_scores"]["intensity"]["tier_key"] == "surgery"


def test_objective_hierarchy_and_negative_only_behavior():
    promoted = [
        {"category": "imaging", "label": "No acute fracture or dislocation", "citation_ids": ["c1"]},
    ]
    out = build_case_severity_index(_eg(), _rm(promoted_findings=promoted), _fp(has_imaging=True))
    assert out["component_scores"]["objective"]["tier_key"] == "imaging_negative_only"

    promoted = [
        {"category": "imaging", "label": "No acute fracture or dislocation", "citation_ids": ["c1"]},
        {"category": "objective_deficit", "label": "Paraspinal spasm noted", "citation_ids": ["c2"]},
    ]
    out = build_case_severity_index(_eg(), _rm(promoted_findings=promoted), _fp(has_imaging=True))
    assert out["component_scores"]["objective"]["tier_key"] == "soft_tissue"


def test_weighted_average_calculation():
    promoted = [{"category": "diagnosis", "label": "Cervical radiculopathy", "citation_ids": ["c9"]}]
    rm = _rm(
        promoted_findings=promoted,
        pt_summary={"date_start": "2025-01-01", "date_end": "2025-04-05", "citation_ids": ["c7"]},
        bucket_evidence={"ed": {"citation_ids": ["c5"]}},
    )
    fp = _fp(has_ed_visit=True, has_imaging=True, has_pt=True)
    out = build_case_severity_index(_eg(), rm, fp)
    # objective=8, intensity=6, duration=6 => 6.9
    assert out["base_csi"] == 6.9


def test_ceiling_precedence_over_floor_when_surgery_present():
    # objective low + no duration but surgery should force >= 8.5
    out = build_case_severity_index(_eg(), _rm(), _fp(has_surgery=True, has_imaging=True))
    assert out["base_csi"] >= 8.5
    assert out["floor_applied"] is False


def test_floor_applies_when_low_objective_and_no_injection_or_surgery():
    # objective=1, intensity moderate, duration high would exceed 5.5 without floor
    rm = _rm(pt_summary={"date_start": "2025-01-01", "date_end": "2025-12-31", "citation_ids": []})
    fp = _fp(has_ed_visit=True, has_imaging=True, has_pt=True)
    out = build_case_severity_index(_eg(), rm, fp)
    assert out["component_scores"]["objective"]["score"] <= 1
    assert out["base_csi"] <= 5.5


def test_risk_penalty_cap_and_separation_from_base():
    eg = _eg(
        extensions={
            "litigation_safe_v1": {"max_gap_days": 120, "days_to_first_care": 30},
            "defense_attack_paths": {"has_prior_similar_injury": True},
        }
    )
    out = build_case_severity_index(eg, _rm(), _fp())
    assert out["risk_penalty"] == 1.0
    assert out["risk_adjusted_csi"] <= out["base_csi"]


def test_support_propagation_and_deterministic_sorting():
    eg = _eg(
        citations=[
            {"citation_id": "c2", "source_document_id": "doc-b", "page_number": 10},
            {"citation_id": "c1", "source_document_id": "doc-a", "page_number": 5},
            {"citation_id": "c3", "source_document_id": "doc-a", "page_number": 11},
        ]
    )
    rm = _rm(
        promoted_findings=[
            {"category": "diagnosis", "label": "Radiculopathy", "citation_ids": ["c2", "c1"]},
            {"category": "imaging", "label": "Disc protrusion", "citation_ids": ["c3"]},
        ],
        pt_summary={"date_start": "2025-01-01", "date_end": "2025-04-01", "citation_ids": ["c1"]},
        bucket_evidence={"ed": {"citation_ids": ["c2"]}},
    )
    fp = _fp(has_ed_visit=True, has_imaging=True, has_pt=True)
    out = build_case_severity_index(eg, rm, fp)
    assert out["support"]["citation_ids"] == sorted(out["support"]["citation_ids"])
    refs = out["support"]["page_refs"]
    assert refs == sorted(refs, key=lambda r: (str(r.get("source_document_id") or ""), int(r.get("page_number") or 0)))


def test_deterministic_repeatability():
    eg = _eg(citations=[{"citation_id": "c1", "source_document_id": "doc", "page_number": 1}])
    rm = _rm(
        promoted_findings=[{"category": "diagnosis", "label": "Radiculopathy", "citation_ids": ["c1"]}],
        pt_summary={"date_start": "2025-01-01", "date_end": "2025-03-01", "citation_ids": ["c1"]},
        bucket_evidence={"ed": {"citation_ids": ["c1"]}},
    )
    fp = _fp(has_ed_visit=True, has_imaging=True, has_pt=True)
    a = build_case_severity_index(eg, rm, fp)
    b = build_case_severity_index(eg, rm, fp)
    assert a == b
