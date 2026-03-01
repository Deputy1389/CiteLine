from __future__ import annotations

from pathlib import Path
from typing import Any


def _canonical_failure_codes(gate_results: dict[str, Any] | None) -> list[str]:
    codes: list[str] = []
    for row in list((gate_results or {}).get("failures") or []):
        if not isinstance(row, dict):
            continue
        src = str(row.get("source") or "").strip().lower()
        code = str(row.get("code") or "").strip().upper()
        if code:
            codes.append(f"{src}:{code}" if src else code)
    # Stable dedupe order
    out: list[str] = []
    seen: set[str] = set()
    for c in codes:
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def build_pipeline_parity_report(
    *,
    mode: str,
    source_pdf: str | Path | None,
    page_text_by_number: dict[int, str] | None,
    projection_entries: list[Any] | None,
    chronology_events: list[Any] | None,
    gaps: list[Any] | None,
    gate_results: dict[str, Any] | None,
) -> dict[str, Any]:
    contract_keys = [
        "report_text",
        "page_text_by_number",
        "projection_entries",
        "chronology_events",
        "gaps",
        "source_pdf",
    ]
    return {
        "schema_version": "pipeline_parity.v1",
        "mode": str(mode or "unknown"),
        "canonical_quality_gate_api": "apps.worker.lib.quality_gates.run_quality_gates",
        "entrypoints": {
            "eval": "scripts.run_case.run_case",
            "production": "apps.worker.pipeline.run_pipeline",
        },
        "quality_gate_contract_keys": contract_keys,
        # Kept stable so existing eval consumers do not need migration.
        "eval_run_quality_gates_kwargs": {
            "source_pdf": (str(source_pdf) if source_pdf else None),
            "page_text_pages": len(dict(page_text_by_number or {})),
            "projection_entries": len(list(projection_entries or [])),
            "chronology_events": len(list(chronology_events or [])),
            "gaps": len(list(gaps or [])),
        },
        "intentional_deltas": [],
        "gate_outcome_snapshot": {
            "overall_pass": bool((gate_results or {}).get("overall_pass", True)),
            "failures_count": len((gate_results or {}).get("failures") or []),
            "failure_codes": _canonical_failure_codes(gate_results),
        },
    }
