"""
Tests for apps/worker/lib/internal_demand_copilot.py — Pass33.

38+ tests covering:
  - Base band mapping (6)
  - Adjustment math incl. guards and caps (12)
  - Anchor percentile, rounding, floor safety (7)
  - Schema contract (4)
  - Strip tests (4)
  - Strategy map determinism (2)
  - Counteroffer classification (5)
  - Demand letter safety constraints (3)
  - Confidence drivers ranked (2)
"""
from __future__ import annotations

import pytest

from apps.worker.lib.internal_demand_copilot import (
    _ADJ_LABELS,
    _apply_band_adjustments,
    _base_band_from_csi,
    _compute_adjustments,
    _compute_anchor,
    _lookup_strategy,
    _SCHEMA_VERSION,
    _MODE_TAG,
    build_internal_demand_package,
    classify_counteroffer,
)
from apps.worker.lib.artifacts_writer import (
    _VALUATION_EXTENSION_KEYS,
    build_export_evidence_graph,
)
from apps.worker.steps.export_render.orchestrator import _MEDIATION_BANNED_KEYS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _csi(i_tier: str = "none", o_tier: str = "no_objective", score: int = 10) -> dict:
    return {
        "score_0_100": score,
        "selected_tiers": {"intensity": i_tier, "objective": o_tier, "duration": "15_60"},
        "inputs_used": {"date_start": None, "date_end": None},
        "profile": "Profile: No objective imaging findings documented; No treatment intensity tier documented; 15-60 day treatment course.",
        "component_labels": {
            "treatment_intensity": "No treatment intensity tier documented",
            "duration": "15-60 day treatment course",
        },
    }


def _empty_eg() -> dict:
    """Minimal evidence graph with empty settlement_feature_pack."""
    return {
        "events": [],
        "gaps": [],
        "extensions": {
            "settlement_feature_pack": {
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
                "has_disability_rating": False,
                "has_impairment_rating": False,
            },
        },
    }


def _fp_update(eg: dict, **kwargs) -> dict:
    """Update settlement_feature_pack keys in an evidence graph."""
    eg["extensions"]["settlement_feature_pack"].update(kwargs)
    return eg


def _specials(total: float) -> dict:
    return {"totals": {"total_charges": str(total)}}


# ── Base Band ─────────────────────────────────────────────────────────────────

class TestBaseBand:
    def test_surgery_intensity_returns_surgical_band(self):
        band, is_surg = _base_band_from_csi(_csi(i_tier="surgery"))
        assert band == [5.5, 9.0]
        assert is_surg is True

    def test_surgical_objective_tier_returns_surgical_band(self):
        band, is_surg = _base_band_from_csi(_csi(o_tier="surgical_indication"))
        assert band == [5.5, 9.0]
        assert is_surg is True

    def test_injection_specialist_returns_injection_band(self):
        band, is_surg = _base_band_from_csi(_csi(i_tier="injection_specialist"))
        assert band == [3.5, 6.0]
        assert is_surg is False

    def test_disc_displacement_returns_disc_radic_band(self):
        band, is_surg = _base_band_from_csi(_csi(o_tier="disc_displacement"))
        assert band == [2.5, 4.5]
        assert is_surg is False

    def test_radiculopathy_objective_returns_disc_radic_band(self):
        band, is_surg = _base_band_from_csi(_csi(o_tier="radiculopathy"))
        assert band == [2.5, 4.5]
        assert is_surg is False

    def test_soft_tissue_returns_soft_tissue_band(self):
        band, _ = _base_band_from_csi(_csi(o_tier="soft_tissue"))
        assert band == [2.0, 3.5]

    def test_no_csi_returns_minimal_band(self):
        band, is_surg = _base_band_from_csi(None)
        assert band == [1.5, 2.5]
        assert is_surg is False

    def test_no_objective_returns_minimal_band(self):
        band, _ = _base_band_from_csi(_csi(o_tier="no_objective"))
        assert band == [1.5, 2.5]


# ── Adjustments ───────────────────────────────────────────────────────────────

def _signals_blank() -> dict:
    return {
        "has_surgery": False,
        "has_injection": False,
        "has_specialist": False,
        "has_radiculopathy": False,
        "has_disc_herniation": False,
        "has_emg_positive": False,
        "has_imaging": False,
        "has_neuro_deficit_keywords": False,
        "has_surgical_indication": False,
        "has_disability": False,
        "has_persistent_neuro": False,
        "multi_level_disc": False,
        "imaging_is_negative": False,
        "duration_days": None,
        "max_gap_days": 0,
        "days_to_first_care": None,
        "pt_count": None,
        "has_prior_similar_injury": False,
    }


class TestAdjustments:
    def test_single_upward_radiculopathy(self):
        s = _signals_blank()
        s["has_radiculopathy"] = True
        s["has_imaging"] = True  # suppress conservative_only_no_imaging
        recs, up, down = _compute_adjustments(s, False, "none")
        up_recs = [r for r in recs if r["direction"] == "up"]
        assert len(up_recs) == 1
        assert up_recs[0]["key"] == "radiculopathy_documented"
        assert up_recs[0]["delta"] == 0.5
        assert up == 0.5
        assert down == 0.0

    def test_single_downward_major_gap(self):
        s = _signals_blank()
        s["max_gap_days"] = 150
        s["has_imaging"] = True  # suppress conservative_only_no_imaging
        recs, up, down = _compute_adjustments(s, False, "none")
        down_recs = [r for r in recs if r["direction"] == "down"]
        assert len(down_recs) == 1
        assert down_recs[0]["key"] == "major_gap_in_care_gt_120_days"
        assert down_recs[0]["delta"] == -1.0
        assert down == 1.0

    def test_combined_up_and_down_math(self):
        s = _signals_blank()
        s["has_radiculopathy"] = True   # +0.5
        s["max_gap_days"] = 150         # -1.0
        s["has_imaging"] = True         # suppress conservative_only_no_imaging
        _, up, down = _compute_adjustments(s, False, "none")
        assert up == 0.5
        assert down == 1.0

    def test_up_cap_enforced_at_2_0(self):
        s = _signals_blank()
        # Many upward signals to exceed 2.0 cap
        s["has_radiculopathy"] = True          # +0.5
        s["multi_level_disc"] = True           # +0.5
        s["has_emg_positive"] = True           # +0.5
        s["has_specialist"] = True             # +0.5
        s["has_disability"] = True             # +0.5  → would be 2.5 total, capped at 2.0
        _, up, _ = _compute_adjustments(s, False, "none")
        assert up == pytest.approx(2.0, abs=0.01)

    def test_down_cap_enforced_at_2_0(self):
        s = _signals_blank()
        s["max_gap_days"] = 150           # -1.0
        s["has_prior_similar_injury"] = True  # -0.5
        s["days_to_first_care"] = 20      # -0.5
        # conservative_only_no_imaging: no imaging + no specialist + no surgery + no injection
        # → -0.5, but cap at 2.0 total
        _, _, down = _compute_adjustments(s, False, "none")
        assert down == pytest.approx(2.0, abs=0.01)

    def test_surgery_floor_after_max_down_pressure(self):
        """Surgical case: band must not fall below [5.0, 8.0] even with max down."""
        base_band = [5.5, 9.0]
        adjusted, _, _ = _apply_band_adjustments(base_band, 0.0, 2.0, is_surgical=True)
        assert adjusted[0] >= 5.0
        assert adjusted[1] >= 8.0

    def test_global_floor_respected(self):
        base_band = [1.5, 2.5]
        adjusted, _, _ = _apply_band_adjustments(base_band, 0.0, 2.0, is_surgical=False)
        assert adjusted[0] >= 1.0
        assert adjusted[1] >= 2.0

    def test_duration_gt_365_replaces_gt_180_not_additive(self):
        """365-day signal must not stack with 180-day signal."""
        s = _signals_blank()
        s["duration_days"] = 400  # >365
        recs, up, _ = _compute_adjustments(s, False, "none")
        duration_keys = [r["key"] for r in recs if "duration" in r["key"]]
        assert "treatment_duration_gt_365_days" in duration_keys
        assert "treatment_duration_gt_180_days" not in duration_keys
        assert up == pytest.approx(1.0, abs=0.01)

    def test_imaging_negative_suppressed_when_radiculopathy_active(self):
        s = _signals_blank()
        s["imaging_is_negative"] = True
        s["has_radiculopathy"] = True   # guard: suppress imaging_negative
        s["has_imaging"] = True
        recs, _, _ = _compute_adjustments(s, False, "none")
        keys = [r["key"] for r in recs]
        assert "imaging_negative_or_minor" not in keys

    def test_imaging_negative_suppressed_when_escalation_present(self):
        s = _signals_blank()
        s["imaging_is_negative"] = True
        s["has_specialist"] = True   # escalation: suppress imaging_negative
        s["has_imaging"] = True
        recs, _, _ = _compute_adjustments(s, False, "injection_specialist")
        keys = [r["key"] for r in recs]
        assert "imaging_negative_or_minor" not in keys

    def test_pt_visits_lt6_suppressed_when_injection_tier(self):
        s = _signals_blank()
        s["pt_count"] = 3
        # i_tier = injection_specialist: guard suppresses pt_visits_lt_6
        recs, _, _ = _compute_adjustments(s, False, "injection_specialist")
        keys = [r["key"] for r in recs]
        assert "pt_visits_lt_6" not in keys

    def test_pt_visits_lt6_suppressed_when_specialist_active(self):
        s = _signals_blank()
        s["pt_count"] = 3
        s["has_specialist"] = True  # guard: escalation present
        recs, _, _ = _compute_adjustments(s, False, "ed_pt")
        keys = [r["key"] for r in recs]
        assert "pt_visits_lt_6" not in keys

    def test_pt_visits_lt6_applies_in_conservative_case(self):
        s = _signals_blank()
        s["pt_count"] = 3
        # No injection, no surgery, no specialist, non-escalation tier
        recs, _, down = _compute_adjustments(s, False, "ed_pt")
        keys = [r["key"] for r in recs]
        assert "pt_visits_lt_6" in keys
        assert down > 0


# ── Anchor ────────────────────────────────────────────────────────────────────

class TestAnchor:
    def test_risk_count_0_uses_90th_percentile(self):
        result = _compute_anchor([2.0, 4.0], 10000.0, 0)
        assert result is not None
        assert result["percentile_used"] == 0.90
        # chosen_mult = 2.0 + 0.9 * 2.0 = 3.8
        assert result["chosen_multiplier"] == pytest.approx(3.8, abs=0.01)

    def test_risk_count_1_uses_80th_percentile(self):
        result = _compute_anchor([2.0, 4.0], 10000.0, 1)
        assert result is not None
        assert result["percentile_used"] == 0.80

    def test_risk_count_ge2_uses_70th_percentile(self):
        result = _compute_anchor([2.0, 4.0], 10000.0, 2)
        assert result is not None
        assert result["percentile_used"] == 0.70

    def test_anchor_rounds_to_nearest_100(self):
        # specials=10000, band=[2.0,4.0], risk_count=0
        # chosen=3.8, raw=38000 → rounds to 38000
        result = _compute_anchor([2.0, 4.0], 10000.0, 0)
        assert result is not None
        assert result["suggested_demand_anchor"] % 100 == 0

    def test_anchor_null_when_no_specials(self):
        result = _compute_anchor([2.0, 4.0], 0.0, 0)
        assert result is None

    def test_anchor_floor_safety(self):
        """Anchor must be >= specials * (low + 0.25)."""
        # Tight band [1.0, 1.5], risk_count=2 → percentile=0.70
        # chosen = 1.0 + 0.7*0.5 = 1.35, anchor = 10000*1.35=13500
        # floor = specials * (1.0+0.25) = 12500 → anchor stays at 13500 (already above floor)
        result = _compute_anchor([1.0, 1.5], 10000.0, 2)
        assert result is not None
        assert result["suggested_demand_anchor"] >= 10000 * (1.0 + 0.25)

    def test_anchor_upper_clamp(self):
        """Anchor must not exceed specials * high."""
        result = _compute_anchor([2.0, 3.0], 10000.0, 0)
        assert result is not None
        assert result["suggested_demand_anchor"] <= 10000 * 3.0


# ── Schema ────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_schema_version(self):
        result = build_internal_demand_package()
        assert result["schema_version"] == _SCHEMA_VERSION
        assert result["schema_version"] == "internal_demand_package.v1"

    def test_mode_tag(self):
        result = build_internal_demand_package()
        assert result["mode"] == _MODE_TAG
        assert result["mode"] == "INTERNAL_ONLY_DO_NOT_EXPORT"

    def test_adjustments_sorted_by_key(self):
        eg = _empty_eg()
        _fp_update(eg, has_radiculopathy=True, has_specialist=True, max_gap_days=150)
        result = build_internal_demand_package(
            evidence_graph=eg,
            csi_internal=_csi(o_tier="radiculopathy", score=70),
        )
        adjs = result["multiplier"]["adjustments"]
        keys = [a["key"] for a in adjs]
        assert keys == sorted(keys)

    def test_support_citation_ids_on_each_adjustment(self):
        eg = _empty_eg()
        _fp_update(eg, has_radiculopathy=True, max_gap_days=150)
        result = build_internal_demand_package(
            evidence_graph=eg,
            csi_internal=_csi(o_tier="radiculopathy", score=70),
        )
        for adj in result["multiplier"]["adjustments"]:
            assert "support_citation_ids" in adj
            assert isinstance(adj["support_citation_ids"], list)


# ── Strip Tests ───────────────────────────────────────────────────────────────

class TestStrip:
    def test_mediation_build_export_excludes_internal_demand_package(self):
        payload = {
            "extensions": {
                "severity_profile": {"tier": "moderate"},
                "internal_demand_package": {"mode": "INTERNAL_ONLY_DO_NOT_EXPORT"},
                "export_mode": "MEDIATION",
            }
        }
        filtered = build_export_evidence_graph(payload, "MEDIATION")
        assert "internal_demand_package" not in filtered.get("extensions", {})

    def test_internal_mode_preserves_internal_demand_package(self):
        payload = {
            "extensions": {
                "severity_profile": {"tier": "moderate"},
                "internal_demand_package": {"mode": "INTERNAL_ONLY_DO_NOT_EXPORT"},
            }
        }
        filtered = build_export_evidence_graph(payload, "INTERNAL")
        assert "internal_demand_package" in filtered.get("extensions", {})

    def test_valuation_extension_keys_contains_key(self):
        assert "internal_demand_package" in _VALUATION_EXTENSION_KEYS

    def test_mediation_banned_keys_contains_key(self):
        assert "internal_demand_package" in _MEDIATION_BANNED_KEYS


# ── Strategy Map ──────────────────────────────────────────────────────────────

class TestStrategyMap:
    def test_deterministic_same_inputs_same_output(self):
        key_a = _lookup_strategy("STRONG", 1)
        key_b = _lookup_strategy("STRONG", 1)
        assert key_a == key_b == "ASSERTIVE_WITH_PREEMPTION"

    def test_low_strength_maps_to_anchor_near_specials(self):
        key = _lookup_strategy("LOW", 0)
        assert key == "ANCHOR_NEAR_SPECIALS"

    def test_strong_no_risk_maps_to_push_high(self):
        assert _lookup_strategy("STRONG", 0) == "PUSH_HIGH_ANCHOR"

    def test_strong_two_risk_maps_to_standard_with_rebuttal(self):
        assert _lookup_strategy("HIGH", 2) == "STANDARD_WITH_REBUTTAL"

    def test_moderate_two_risk_maps_to_build_case(self):
        assert _lookup_strategy("MODERATE", 2) == "BUILD_CASE"


# ── Counteroffer ──────────────────────────────────────────────────────────────

class TestCounteroffer:
    def test_lowball(self):
        result = classify_counteroffer(10000, 20000, [3.0, 5.0])
        assert result["classification"] == "LOWBALL"  # 10k < 20k*1.5=30k

    def test_below_range(self):
        # specials=20000, band=[3.0,5.0] → low=60000, offer=50000 < 60000
        result = classify_counteroffer(50000, 20000, [3.0, 5.0])
        assert result["classification"] == "BELOW_RANGE"

    def test_negotiable(self):
        # specials=20000, band=[3.0,5.0] → low=60k, high=100k, mid=80k
        # offer=70000 is between 60k and 80k → NEGOTIABLE
        result = classify_counteroffer(70000, 20000, [3.0, 5.0])
        assert result["classification"] == "NEGOTIABLE"

    def test_strong_offer(self):
        # offer=90000 between mid(80k) and high(100k)
        result = classify_counteroffer(90000, 20000, [3.0, 5.0])
        assert result["classification"] == "STRONG_OFFER"

    def test_above_expectation(self):
        # offer=120000 > high(100k)
        result = classify_counteroffer(120000, 20000, [3.0, 5.0])
        assert result["classification"] == "ABOVE_EXPECTATION"

    def test_unknown_when_no_specials(self):
        result = classify_counteroffer(50000, 0, [3.0, 5.0])
        assert result["classification"] == "UNKNOWN"


# ── Demand Letter Safety ──────────────────────────────────────────────────────

class TestDemandLetterSafety:
    def test_block_f_absent_when_no_specials(self):
        eg = _empty_eg()
        result = build_internal_demand_package(
            evidence_graph=eg,
            csi_internal=_csi(score=50),
            damages_structured=None,
        )
        blocks = result["demand_letter_draft"]["blocks"]
        assert "F_DEMAND" not in blocks

    def test_block_f_absent_when_specials_zero(self):
        eg = _empty_eg()
        result = build_internal_demand_package(
            evidence_graph=eg,
            csi_internal=_csi(score=50),
            damages_structured=_specials(0),
        )
        blocks = result["demand_letter_draft"]["blocks"]
        assert "F_DEMAND" not in blocks

    def test_block_f_no_verdict_language(self):
        eg = _empty_eg()
        result = build_internal_demand_package(
            evidence_graph=eg,
            csi_internal=_csi(o_tier="radiculopathy", score=80),
            damages_structured=_specials(42000),
        )
        f_text = result["demand_letter_draft"]["blocks"].get("F_DEMAND", "")
        for forbidden in ("jury", "permanent", "multiplier", "CSI", "score_0_100"):
            assert forbidden.lower() not in f_text.lower(), \
                f"Block F must not contain '{forbidden}'"

    def test_demand_letter_labeled_internal_draft(self):
        eg = _empty_eg()
        result = build_internal_demand_package(
            evidence_graph=eg,
            csi_internal=_csi(score=50),
            damages_structured=_specials(30000),
        )
        label = result["demand_letter_draft"]["label"]
        assert "INTERNAL DRAFT" in label
        assert "DO NOT EXPORT" in label


# ── Confidence Drivers Ranked ─────────────────────────────────────────────────

class TestConfidenceDriversRanked:
    def test_weights_match_adjustment_deltas(self):
        eg = _empty_eg()
        _fp_update(eg, has_radiculopathy=True, has_specialist=True)
        result = build_internal_demand_package(
            evidence_graph=eg,
            csi_internal=_csi(o_tier="radiculopathy", score=70),
        )
        ranked = result["strength_summary"]["confidence_drivers_ranked"]
        adj_map = {
            a["key"]: a["delta"]
            for a in result["multiplier"]["adjustments"]
            if a["direction"] == "up"
        }
        for item in ranked:
            # weight in ranked should match delta in adjustments
            assert item["weight"] == pytest.approx(adj_map[item["key"]], abs=0.01)

    def test_at_most_3_drivers_ranked(self):
        eg = _empty_eg()
        _fp_update(eg,
            has_radiculopathy=True,
            has_specialist=True,
            has_emg_positive=True,
            has_disability_rating=True,
        )
        result = build_internal_demand_package(
            evidence_graph=eg,
            csi_internal=_csi(o_tier="radiculopathy", score=80),
        )
        ranked = result["strength_summary"]["confidence_drivers_ranked"]
        assert len(ranked) <= 3


# ── Full Integration (smoke) ──────────────────────────────────────────────────

class TestIntegrationSmoke:
    def test_full_build_no_exception_empty_inputs(self):
        result = build_internal_demand_package()
        assert result["schema_version"] == "internal_demand_package.v1"
        assert result["mode"] == "INTERNAL_ONLY_DO_NOT_EXPORT"

    def test_full_build_with_specials_has_anchor(self):
        eg = _empty_eg()
        _fp_update(eg, has_radiculopathy=True, has_specialist=True)
        result = build_internal_demand_package(
            evidence_graph=eg,
            csi_internal=_csi(o_tier="radiculopathy", i_tier="injection_specialist", score=80),
            damages_structured=_specials(42000),
        )
        assert result["anchor"] is not None
        assert result["anchor"]["suggested_demand_anchor"] > 0
        assert "F_DEMAND" in result["demand_letter_draft"]["blocks"]

    def test_full_build_mediation_strip_double_check(self):
        """End-to-end: build package, put in evidence graph, strip for MEDIATION."""
        eg_payload = {
            "extensions": {
                "severity_profile": {"tier": "moderate"},
                "internal_demand_package": build_internal_demand_package(
                    evidence_graph=_empty_eg(),
                    csi_internal=_csi(score=60),
                    damages_structured=_specials(30000),
                ),
            }
        }
        mediation_out = build_export_evidence_graph(eg_payload, "MEDIATION")
        assert "internal_demand_package" not in mediation_out.get("extensions", {})

        internal_out = build_export_evidence_graph(eg_payload, "INTERNAL")
        assert "internal_demand_package" in internal_out.get("extensions", {})
