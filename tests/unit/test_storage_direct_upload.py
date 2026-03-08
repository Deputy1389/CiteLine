from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.shared import storage


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (
            "/object/upload/sign/documents/demo.pdf?token=abc",
            "https://example.supabase.co/storage/v1/object/upload/sign/documents/demo.pdf?token=abc",
        ),
        (
            "/storage/v1/object/upload/sign/documents/demo.pdf?token=abc",
            "https://example.supabase.co/storage/v1/object/upload/sign/documents/demo.pdf?token=abc",
        ),
        (
            "https://example.supabase.co/storage/v1/object/upload/sign/documents/demo.pdf?token=abc",
            "https://example.supabase.co/storage/v1/object/upload/sign/documents/demo.pdf?token=abc",
        ),
    ],
)
def test_normalize_supabase_signed_url(monkeypatch: pytest.MonkeyPatch, raw_url: str, expected: str) -> None:
    monkeypatch.setattr(storage, "SUPABASE_REST_URL", "https://example.supabase.co")
    assert storage._normalize_supabase_signed_url(raw_url) == expected


def test_create_signed_upload_url_normalizes_provider_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage, "USE_SUPABASE_STORAGE", True)
    monkeypatch.setattr(storage, "SUPABASE_REST_URL", "https://example.supabase.co")
    monkeypatch.setattr(storage, "SUPABASE_SERVICE_KEY", "service-key")

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"url": "/object/upload/sign/documents/demo.pdf?token=test-token"},
            text='{"url":"/object/upload/sign/documents/demo.pdf?token=test-token"}',
        )

    monkeypatch.setattr(storage.requests, "post", fake_post)

    signed = storage.create_signed_upload_url("documents", "demo.pdf")
    assert signed["signed_url"] == "https://example.supabase.co/storage/v1/object/upload/sign/documents/demo.pdf?token=test-token"
    assert signed["token"] == "test-token"
