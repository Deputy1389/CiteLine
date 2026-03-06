"""
apps/worker/lib/observability.py — Pass 042

Production observability helpers:
  - RunErrorClass: canonical error taxonomy (enum)
  - _classify_error(): maps exceptions to RunErrorClass
  - stage_timer(): context manager for per-stage timing
  - write_run_observability(): writes metadata + invariant results + metrics
    to the DB. NEVER raises — observability must not block run completion.
"""
from __future__ import annotations

import contextlib
import json
import logging
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Error taxonomy ─────────────────────────────────────────────────────────────

class RunErrorClass(str, Enum):
    """Canonical error classes for run.error_class column.

    Keep this small. Add new values only with a PR that also updates
    the operator queries in reference/operator_queries.sql.
    """
    EXTRACTION_FAILURE = "extraction_failure"   # OCR / text acquisition failure
    RENDER_CRASH       = "render_crash"          # PDF generation failure
    TIMEOUT            = "timeout"               # stage exceeded time limit
    PIPELINE_ERROR     = "pipeline_error"        # catch-all; investigate if volume rises


def _classify_error(exc: Exception) -> str:
    """Map an exception to a canonical RunErrorClass string.

    Uses isinstance() checks against typed exceptions where available.
    Falls through to PIPELINE_ERROR for unknown types — never free-text.
    """
    name = type(exc).__qualname__

    # Extraction / text acquisition
    if "TextAcquisitionError" in name or "OCRError" in name:
        return RunErrorClass.EXTRACTION_FAILURE

    # Render / PDF generation
    if "RenderError" in name or "PDFGenerationError" in name or "ReportLabError" in name:
        return RunErrorClass.RENDER_CRASH

    # Timeout
    if isinstance(exc, TimeoutError) or "TimeoutError" in name or "DeadlineExceeded" in name:
        return RunErrorClass.TIMEOUT

    # Default catch-all
    return RunErrorClass.PIPELINE_ERROR


# ── Stage timing ──────────────────────────────────────────────────────────────

class _StageTimings:
    """Accumulates per-stage elapsed times across a pipeline run."""
    def __init__(self) -> None:
        self._times: dict[str, float] = {}

    @contextlib.contextmanager
    def timer(self, stage: str, run_id: str = "", **meta: Any):
        """Context manager that records elapsed_ms for a pipeline stage."""
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self._times[stage] = elapsed_ms
            logger.info(
                json.dumps({
                    "run_id": run_id,
                    "stage": stage,
                    "event": "complete",
                    "duration_ms": elapsed_ms,
                    **{k: str(v) for k, v in meta.items()},
                })
            )

    def as_dict(self) -> dict[str, float]:
        return dict(self._times)


def make_stage_timings() -> _StageTimings:
    """Create a fresh stage-timing accumulator for one pipeline run."""
    return _StageTimings()


# ── DB write (never raises) ───────────────────────────────────────────────────

def write_run_observability(
    *,
    run_id: str,
    session: Any,
    run_row: Any,
    config: Any | None = None,
    ext: dict | None = None,
    page_count: int | None = None,
    packet_bytes: int | None = None,
    exc: Exception | None = None,
    invariant_results: list[dict] | None = None,
    stage_timings: dict[str, float] | None = None,
) -> None:
    """Write observability metadata to the DB inside the caller's session.

    MUST be called AFTER run_row.status is committed (authoritative write first).
    All writes are inside a try/except — a DB hiccup must never surface as a
    run failure. Failures are logged and silently swallowed.

    Args:
        run_id: the current run ID
        session: active SQLAlchemy session (caller owns commit/rollback)
        run_row: RunORM instance already flushed with terminal status
        config: RunConfig (optional) — used for signal_layer_version
        ext: evidence_graph.extensions dict (optional) — reads leverage_policy
        page_count: total pages in packet
        packet_bytes: total bytes in packet
        exc: exception that caused failure, or None on success
        invariant_results: list of harness result dicts (invariant, passed, detail)
        stage_timings: {stage_name: elapsed_ms} from _StageTimings.as_dict()
    """
    try:
        # Import here to avoid circular imports at module load time
        from packages.db.models import InvariantResult, RunMetric

        # ── Metadata columns ──────────────────────────────────────────────────
        if config is not None:
            slv = getattr(config, "signal_layer_version", None)
            if slv:
                run_row.signal_layer_version = str(slv)

        lev_policy = (ext or {}).get("leverage_policy") or {}
        if isinstance(lev_policy, dict):
            pv = lev_policy.get("version")
            pf = lev_policy.get("fingerprint")
            if pv:
                run_row.policy_version = str(pv)[:50]
            if pf:
                run_row.policy_fingerprint = str(pf)[:16]

        if page_count is not None:
            run_row.packet_page_count = int(page_count)
        if packet_bytes is not None:
            run_row.packet_bytes = int(packet_bytes)
        if exc is not None:
            run_row.error_class = _classify_error(exc)

        session.flush()

        # ── Invariant results ─────────────────────────────────────────────────
        for result in (invariant_results or []):
            check = result.get("invariant") or result.get("check_name") or ""
            passed = bool(result.get("passed", True))
            detail = str(result.get("detail") or result.get("outcome") or "")[:2000]
            severity = "fail" if not passed else "info"
            session.add(InvariantResult(
                run_id=run_id,
                check_name=check,
                passed=passed,
                outcome=detail,
                severity=severity,
            ))

        # ── Stage timing metrics ──────────────────────────────────────────────
        for stage, elapsed_ms in (stage_timings or {}).items():
            session.add(RunMetric(
                run_id=run_id,
                metric_name=f"{stage}_time_ms",
                metric_value_num=float(elapsed_ms),
            ))

        session.flush()

    except Exception as obs_exc:
        logger.warning(
            "[%s] observability write failed — run outcome unaffected: %s",
            run_id,
            obs_exc,
        )
