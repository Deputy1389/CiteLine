from __future__ import annotations

from packages.shared.utils.claim_utils import extract_body_region, parse_iso, stable_id


def test_parse_iso_extracts_embedded_date() -> None:
    parsed = parse_iso("2025-04-07 (time not documented)")
    assert parsed is not None
    assert parsed.isoformat() == "2025-04-07"


def test_parse_iso_rejects_invalid_date() -> None:
    assert parse_iso("2025-99-07") is None
    assert parse_iso("not-a-date") is None


def test_stable_id_is_deterministic() -> None:
    a = stable_id(["INJURY_DX", "2025-04-07", "lumbar"])
    b = stable_id(["INJURY_DX", "2025-04-07", "lumbar"])
    assert a == b
    assert len(a) == 16


def test_extract_body_region_regex_fallback() -> None:
    assert extract_body_region("Patient reports neck pain after MVC.") == "cervical"
    assert extract_body_region("No region-specific complaint documented.") == "general"

