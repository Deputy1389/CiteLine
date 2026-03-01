from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any


_VALUATION_EXTENSION_KEYS = {
    "case_severity_index",
    "settlement_model_report",
    "settlement_leverage_model",
    "settlement_feature_pack",
    "defense_attack_map",
    "internal_demand_package",
}

_MEDIATION_EXTENSION_ALLOWLIST = {
    "severity_profile",
    "export_mode",
    "export_artifacts_metadata",
    "renderer_manifest",
    "litigation_safe_v1",
    "claim_context_alignment",
    "claim_rows",
    "causation_chains",
    "citation_fidelity",
    "case_collapse_candidates",
    "contradiction_matrix",
    "narrative_duality",
    "comparative_pattern_engine",
    "pt_encounters",
    "pt_count_reported",
    "pt_reconciliation",
    "missing_records",
    "patient_partitions",
    "provider_resolution_quality",
    "sprint4d_invariants",
    "quality_gate",
    "extraction_metrics",
    "page_quality_assessment",
    "llm_polish_applied",
}


def write_artifact_json(name: str, obj: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


def build_export_evidence_graph(payload: dict[str, Any], export_mode: str) -> dict[str, Any]:
    """
    Build a mode-safe evidence graph payload for artifact serialization.
    Never mutates caller payload.
    """
    out = copy.deepcopy(payload or {})
    mode = str(export_mode or "").strip().upper()
    if mode != "MEDIATION":
        return out
    ext = out.get("extensions")
    if not isinstance(ext, dict):
        out["extensions"] = {"export_mode": "MEDIATION"}
        return out
    safe_ext: dict[str, Any] = {}
    for key in sorted(_MEDIATION_EXTENSION_ALLOWLIST):
        if key in ext:
            safe_ext[key] = ext[key]
    # Explicitly enforce mode and scrub valuation-like keys by family as defense-in-depth.
    safe_ext["export_mode"] = "MEDIATION"
    for key in list(safe_ext.keys()):
        low = str(key).strip().lower()
        if (
            key in _VALUATION_EXTENSION_KEYS
            or "settlement" in low
            or low.startswith("sli")
            or "valuation" in low
            or "negotiation_posture" in low
        ):
            safe_ext.pop(key, None)
    out["extensions"] = safe_ext
    return out


def write_evidence_graph_artifact(
    payload: dict[str, Any],
    export_mode: str,
    out_dir: Path,
    name: str = "evidence_graph.json",
) -> Path:
    """
    Single writer for evidence graph artifacts. Ensures mode-safe filtering.
    """
    return write_artifact_json(name, build_export_evidence_graph(payload, export_mode), out_dir)


def safe_copy(src_path: Path, dst_dir: Path, dst_name: str | None = None) -> Path | None:
    if not src_path or not src_path.exists():
        return None
    dst_dir.mkdir(parents=True, exist_ok=True)
    dest = dst_dir / (dst_name or src_path.name)
    shutil.copyfile(src_path, dest)
    return dest


def validate_artifacts_exist(manifest: dict[str, str | None]) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for key, value in manifest.items():
        if value is None:
            continue
        p = Path(value)
        if not p.exists():
            missing.append(key)
    return (len(missing) == 0), missing
