from __future__ import annotations

from apps.worker.project.chronology import _dynamic_target_rows


def test_dynamic_target_rows_small_packet():
    assert _dynamic_target_rows(substantive_count=6, care_window_days=5, total_pages=5) == 6
    assert _dynamic_target_rows(substantive_count=20, care_window_days=5, total_pages=5) == 10


def test_dynamic_target_rows_moderate_packet():
    assert _dynamic_target_rows(substantive_count=50, care_window_days=60, total_pages=50) == 40
    assert _dynamic_target_rows(substantive_count=12, care_window_days=60, total_pages=50) == 12


def test_dynamic_target_rows_long_care_window_large_packet():
    assert _dynamic_target_rows(substantive_count=200, care_window_days=400, total_pages=500) == 80
    assert _dynamic_target_rows(substantive_count=70, care_window_days=400, total_pages=1000) == 70
