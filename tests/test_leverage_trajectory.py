"""
test_leverage_trajectory.py — Pass 38

Tests for Leverage Trajectory computation.
"""
import pytest
from apps.worker.lib.leverage_trajectory import compute_leverage_trajectory
from packages.shared.models.domain import InvariantGuard, LeverageTrajectory


def test_trajectory_disabled_on_missing_guard():
    signals = {"escalation_events": [{"date": "2024-10-01", "level": 1, "kind": "ED"}]}
    res = compute_leverage_trajectory(signals, guard=None)
    assert res.enabled is False
    assert res.guard_status == "GUARD_MISSING"


def test_trajectory_empty_on_no_signals():
    # Pass guard check
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint="abc",
    )
    # signals_fingerprint mismatch is ignored for empty signals test if we don't care about validation logic
    # but compute_leverage_trajectory calls _validate_guard which checks signals.
    # So we need to match the fingerprint.
    import hashlib, json
    signals = {"escalation_events": []}
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )

    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert res.guard_status == "PASS"
    assert res.peak_level is None
    assert res.monthly_levels == []


def test_trajectory_pattern_flat():
    signals = {"escalation_events": [{"date": "2024-10-01", "level": 2, "kind": "PT_START"}]}
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert res.pattern == "Flat"
    assert res.peak_level == 2


def test_trajectory_pattern_rising():
    signals = {
        "escalation_events": [
            {"date": "2024-10-01", "level": 1, "kind": "ED"},
            {"date": "2024-11-01", "level": 4, "kind": "INJECTION"},
        ]
    }
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert res.pattern == "Rising"
    assert res.peak_level == 4
    assert res.time_to_peak_days == 31


def test_trajectory_pattern_late_escalation():
    signals = {
        "escalation_events": [
            {"date": "2024-01-01", "level": 2, "kind": "PT_START"},
            {"date": "2024-08-01", "level": 5, "kind": "SURGERY"},
        ]
    }
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert res.pattern == "Late Escalation"
    assert res.peak_level == 5
    assert res.time_to_peak_days > 180


def test_trajectory_markers_capped():
    signals = {
        "escalation_events": [
            {"date": f"2024-{m:02d}-01", "level": m, "kind": f"KIND_{m}"}
            for m in range(1, 10)
        ]
    }
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert len(res.markers) <= 5


def test_trajectory_pattern_stepped():
    """Stepped pattern: peak >= 4, num_level_increases >= 3."""
    signals = {
        "escalation_events": [
            {"date": "2024-10-01", "level": 1, "kind": "ED"},
            {"date": "2024-11-01", "level": 2, "kind": "PT_START"},
            {"date": "2024-12-01", "level": 3, "kind": "IMAGING"},
            {"date": "2025-03-01", "level": 4, "kind": "INJECTION"},
        ]
    }
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert res.pattern == "Stepped"
    assert res.peak_level == 4


def test_trajectory_injection_yields_peak_level_4():
    """Injection event should yield peak_level >= 4."""
    signals = {
        "escalation_events": [
            {"date": "2024-10-01", "level": 1, "kind": "ED"},
            {"date": "2024-12-01", "level": 4, "kind": "INJECTION"},
        ]
    }
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert res.peak_level == 4


def test_trajectory_surgery_yields_peak_level_5():
    """Surgery event should yield peak_level == 5."""
    signals = {
        "escalation_events": [
            {"date": "2024-10-01", "level": 1, "kind": "ED"},
            {"date": "2024-12-01", "level": 5, "kind": "SURGERY"},
        ]
    }
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert res.peak_level == 5


def test_trajectory_forward_fill_deterministic():
    """Gap months should be forward-filled with previous level."""
    signals = {
        "escalation_events": [
            {"date": "2024-10-01", "level": 2, "kind": "PT_START"},
            {"date": "2025-02-01", "level": 3, "kind": "IMAGING"},
        ]
    }
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    # Should have levels for Oct, Nov, Dec, Jan, Feb
    monthly_dict = dict(res.monthly_levels)
    # Gap months should have level 2 (forward-filled from PT_START)
    assert monthly_dict.get("2024-11") == 2
    assert monthly_dict.get("2024-12") == 2
    assert monthly_dict.get("2025-01") == 2


def test_trajectory_ed_visit_only_flat():
    """Single ED visit should yield Flat pattern."""
    signals = {
        "escalation_events": [
            {"date": "2024-10-01", "level": 1, "kind": "ED"},
        ]
    }
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert res.pattern == "Flat"
    assert res.peak_level == 1


def test_trajectory_suppresses_undated_events_instead_of_asserting():
    signals = {
        "escalation_events": [
            {"date": "", "level": 4, "kind": "INJECTION"},
            {"date": "2024-10-01", "level": 1, "kind": "ED"},
        ]
    }
    import hashlib, json
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="case1",
        invariant_run_id="run1",
        pass_status=True,
        artifact_fingerprint="abc",
        signals_fingerprint=fp,
    )
    res = compute_leverage_trajectory(signals, guard=guard)
    assert res.enabled is True
    assert res.suppressed_undated_count == 1
    assert res.peak_level == 1


# ── Pass 40: INV-E1 tests ─────────────────────────────────────────────────────

def test_markers_have_source_anchor():
    """E1: All enabled markers must have source_anchor after Pass 40."""
    import hashlib, json
    signals = {
        "escalation_events": [
            {"date": "2024-06-15", "level": 4, "kind": "INJECTION",
             "source_anchor": "abc123def456abcd"},
        ],
    }
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="test",
        invariant_run_id="test",
        pass_status=True,
        artifact_fingerprint="a" * 64,
        signals_fingerprint=fp,
    )
    traj = compute_leverage_trajectory(signals, guard)
    assert traj.enabled is True
    assert len(traj.markers) > 0
    assert all(m.source_anchor is not None for m in traj.markers), \
        "All enabled markers must have source_anchor"


def test_source_anchor_is_stable():
    """D1 / INV-E1: source_anchor must be identical across two derivations of the same data."""
    from apps.worker.lib.settlement_features import _compute_source_anchor
    anchor1 = _compute_source_anchor("2024-06-15", "INJECTION", [42, 43])
    anchor2 = _compute_source_anchor("2024-06-15", "INJECTION", [43, 42])  # different order
    assert anchor1 == anchor2, "source_anchor must be stable regardless of page number order"
    anchor3 = _compute_source_anchor("2024-06-15", "INJECTION", [42, 44])  # different pages
    assert anchor1 != anchor3, "Different pages must produce different anchor"


# ── Pass 41: INV-E2 test ──────────────────────────────────────────────────────

def test_no_escalation_if_only_low_confidence_signal():
    """INV-E2 (Option B): A single low-confidence event must not produce a trajectory marker.

    When all escalation_events have confidence < 0.80, the filtered_events list
    is empty, no markers are produced, and peak_level is None.
    """
    import hashlib, json

    # Event with confidence=0.50 — below the 0.80 INV-E2 threshold
    signals = {
        "escalation_events": [
            {
                "date": "2024-10-01",
                "level": 4,
                "kind": "INJECTION",
                "confidence": 0.50,  # explicitly low-confidence
                "source_anchor": "deadbeef12345678",
            }
        ]
    }
    fp = hashlib.sha256(json.dumps(signals, sort_keys=True, default=str).encode()).hexdigest()
    guard = InvariantGuard(
        case_id="test_inv_e2",
        invariant_run_id="pass041_test",
        pass_status=True,
        artifact_fingerprint="a" * 64,
        signals_fingerprint=fp,
    )

    traj = compute_leverage_trajectory(signals, guard)

    assert traj.enabled is True, "Trajectory should still be enabled"
    assert traj.peak_level is None, (
        f"Low-confidence event must not contribute to peak_level — got {traj.peak_level}"
    )
    assert traj.markers == [], (
        f"Low-confidence event must not produce markers — got {traj.markers}"
    )
    assert traj.suppressed_low_confidence_count == 1, (
        f"Expected 1 suppressed event, got {traj.suppressed_low_confidence_count}"
    )
