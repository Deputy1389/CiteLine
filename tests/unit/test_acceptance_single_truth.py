from __future__ import annotations

from scripts.verify_litigation_export_acceptance import _canonical_gate_snapshot


def test_canonical_gate_snapshot_reads_pipeline_parity_payload() -> None:
    eg = {
        "extensions": {
            "pipeline_parity_report": {
                "gate_outcome_snapshot": {
                    "overall_pass": False,
                    "failures_count": 2,
                    "failure_codes": ["luqa:L1", "attorney:A2"],
                }
            }
        }
    }
    snap = _canonical_gate_snapshot(eg)
    assert snap is not None
    assert snap["overall_pass"] is False
    assert snap["failures_count"] == 2
    assert snap["failure_codes"] == ["luqa:L1", "attorney:A2"]

