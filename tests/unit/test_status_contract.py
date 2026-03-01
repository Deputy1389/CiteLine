from apps.api.routes.exports import _normalize_run_status as normalize_export_status
from apps.api.routes.runs import _normalize_run_status as normalize_run_status


def test_status_normalization_maps_completed_to_success() -> None:
    assert normalize_run_status("completed") == "success"
    assert normalize_export_status("completed") == "success"


def test_status_normalization_accepts_canonical_statuses() -> None:
    for status in ("pending", "running", "success", "partial", "needs_review", "failed"):
        assert normalize_run_status(status) == status
        assert normalize_export_status(status) == status


def test_status_normalization_falls_back_to_failed_for_unknown() -> None:
    assert normalize_run_status("weird") == "failed"
    assert normalize_export_status("weird") == "failed"
