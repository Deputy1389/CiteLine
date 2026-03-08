from __future__ import annotations

import logging
import os
import threading
import time

from packages.db.database import get_session

logger = logging.getLogger("linecite.upload_orphan_sweeper")


def sweeper_enabled() -> bool:
    raw = os.getenv("ENABLE_UPLOAD_ORPHAN_SWEEPER", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def sweep_interval_seconds() -> int:
    return max(60, int(os.getenv("UPLOAD_ORPHAN_SWEEP_INTERVAL_SECONDS", "1800")))


def run_upload_orphan_sweep_once() -> dict[str, int]:
    from apps.api.routes.documents import sweep_orphaned_direct_uploads

    with get_session() as db:
        return sweep_orphaned_direct_uploads(db)


def _sweeper_loop(stop_event: threading.Event) -> None:
    interval = sweep_interval_seconds()
    logger.info("Upload orphan sweeper started interval_seconds=%s", interval)
    while not stop_event.is_set():
        try:
            result = run_upload_orphan_sweep_once()
            if result.get("deleted"):
                logger.info("Upload orphan sweep deleted=%s listed=%s skipped=%s", result.get("deleted"), result.get("listed"), result.get("skipped"))
        except Exception:
            logger.exception("Upload orphan sweep failed")
        stop_event.wait(interval)
    logger.info("Upload orphan sweeper stopped")


def start_upload_orphan_sweeper() -> tuple[threading.Thread, threading.Event] | None:
    if not sweeper_enabled():
        return None
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_sweeper_loop,
        args=(stop_event,),
        name="upload-orphan-sweeper",
        daemon=True,
    )
    thread.start()
    return thread, stop_event
