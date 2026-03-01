"""Unit tests for settlement_posture_pdf.py renderer."""
import pytest
from apps.worker.steps.export_render.settlement_posture_pdf import render_settlement_posture_page


def _smr(**kwargs) -> dict:
    base = {
        "schema_version": "smr.v1",
        "settlement_leverage_index": 0.45,
        "recommended_posture": "BUILD_CASE",
        "case_severity_index": 6.0,
        "flags_triggered": 0,
        "strengths": [],
        "risk_factors": [],
        "posture_text": "This case has documented objective findings.",
    }
    base.update(kwargs)
    return base


def _dam(flags=None) -> dict:
    return {
        "schema_version": "dam.v2",
        "flags_triggered": len([f for f in (flags or []) if f.get("triggered")]),
        "flags": flags or [],
    }


def _csi(**kwargs) -> dict:
    base = {
        "schema_version": "csi.v1",
        "case_severity_index": 6.0,
        "duration_score": 6,
        "treatment_intensity_score": 4,
        "objective_finding_score": 8,
        "profile": "Moderate-high severity injury.",
        "component_labels": {
            "duration": "60–180 days",
            "treatment_intensity": "ED + PT",
            "objective_finding": "Radiculopathy documented",
        },
    }
    base.update(kwargs)
    return base


def test_pdf_renders_bytes_for_valid_input():
    result = render_settlement_posture_page("test-run-001", _smr(), _dam(), _csi())
    assert result is not None
    assert isinstance(result, bytes)
    assert len(result) > 0
    # PDF magic bytes
    assert result[:4] == b"%PDF"


def test_pdf_returns_none_on_none_inputs():
    # None inputs should still produce a valid (empty) page, not crash
    result = render_settlement_posture_page("test-run-002", None, None, None)
    # May return valid PDF with minimal content or None — just must not raise
    assert result is None or (isinstance(result, bytes) and result[:4] == b"%PDF")


def test_pdf_with_triggered_flags():
    dam = _dam(flags=[
        {
            "flag_id": "CARE_GAP_OVER_30_DAYS",
            "triggered": True,
            "severity": "HIGH",
            "label": "Gap in Care (>30 days)",
            "detail": "179-day gap detected between 2024-12-01 and 2025-05-29.",
            "defense_argument": "A 179-day gap suggests the condition resolved.",
            "plaintiff_counter": "Treatment gaps are explained by scheduling constraints.",
            "citation_ids": ["gap-001"],
            "source_type": "gap",
        },
        {
            "flag_id": "CONSERVATIVE_CARE_ONLY",
            "triggered": True,
            "severity": "MED",
            "label": "Conservative Care Only",
            "detail": "No surgical procedure or injection documented.",
            "defense_argument": "Conservative-only treatment indicates mild injury.",
            "plaintiff_counter": "Conservative management is clinically appropriate.",
            "citation_ids": [],
            "source_type": "event",
        },
    ])
    smr = _smr(
        flags_triggered=2,
        strengths=["Positive MRI / imaging findings documented"],
        risk_factors=["Gap in Care (>30 days) [HIGH]", "Conservative Care Only [MED]"],
    )
    result = render_settlement_posture_page("test-run-003", smr, dam, _csi())
    assert result is not None
    assert result[:4] == b"%PDF"
    assert len(result) > 2000


def test_pdf_with_high_severity_case():
    smr = _smr(
        recommended_posture="PUSH_HIGH_ANCHOR",
        settlement_leverage_index=0.82,
        case_severity_index=9.3,
        strengths=[
            "Positive MRI / imaging findings documented",
            "Surgical procedure performed",
            "Permanent impairment rating documented",
        ],
        risk_factors=[],
        posture_text="High leverage — surgical case with objective findings.",
    )
    result = render_settlement_posture_page("test-run-004", smr, _dam(), _csi(case_severity_index=9.3))
    assert result is not None
    assert result[:4] == b"%PDF"


def test_pdf_never_raises():
    """Renderer must never raise, even with garbage inputs."""
    try:
        result = render_settlement_posture_page("bad-run", "not-a-dict", [1, 2, 3], {"broken": True})
        # Either returns bytes or None — never raises
        assert result is None or isinstance(result, bytes)
    except Exception as exc:
        pytest.fail(f"Renderer raised unexpectedly: {exc}")


def test_pdf_bytes_are_valid_pdf_structure():
    """Check that the returned bytes are a structurally valid PDF."""
    result = render_settlement_posture_page(
        "test-run-005",
        _smr(strengths=["Surgery performed"], risk_factors=["Gap [HIGH]"]),
        _dam(),
        _csi(),
    )
    assert result is not None
    assert b"%%EOF" in result or b"xref" in result or b"startxref" in result
