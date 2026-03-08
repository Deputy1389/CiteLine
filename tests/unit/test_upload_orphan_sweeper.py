from __future__ import annotations

import os

from apps.api import upload_orphan_sweeper


def test_sweeper_enabled_env(monkeypatch):
    monkeypatch.setenv("ENABLE_UPLOAD_ORPHAN_SWEEPER", "true")
    assert upload_orphan_sweeper.sweeper_enabled() is True
    monkeypatch.setenv("ENABLE_UPLOAD_ORPHAN_SWEEPER", "false")
    assert upload_orphan_sweeper.sweeper_enabled() is False


def test_run_upload_orphan_sweep_once_uses_documents_helper(monkeypatch):
    called = {}

    class DummyCtx:
        def __enter__(self):
            return "db"

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(upload_orphan_sweeper, "get_session", lambda: DummyCtx())

    from apps.api.routes import documents as documents_route

    monkeypatch.setattr(
        documents_route,
        "sweep_orphaned_direct_uploads",
        lambda db: called.setdefault("result", {"listed": 3, "deleted": 1, "skipped": 2}),
    )

    result = upload_orphan_sweeper.run_upload_orphan_sweep_once()
    assert result == {"listed": 3, "deleted": 1, "skipped": 2}


def test_start_upload_orphan_sweeper_respects_env(monkeypatch):
    monkeypatch.setenv("ENABLE_UPLOAD_ORPHAN_SWEEPER", "false")
    assert upload_orphan_sweeper.start_upload_orphan_sweeper() is None
