from __future__ import annotations

import copy
import hashlib
import json
import os
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
    "visit_abstraction_registry",
    "provider_role_registry",
    "diagnosis_registry",
    "injury_clusters",
    "injury_cluster_severity",
    "treatment_escalation_path",
    "causation_timeline_registry",
    "visit_bucket_quality",
    "registry_contract_version",
    "sprint4d_invariants",
    "quality_gate",
    "extraction_metrics",
    "page_quality_assessment",
    "llm_polish_applied",
    "invariant_attestation",
    "leverage_index_result",
    "leverage_trajectory",
    "leverage_policy",
}


def write_artifact_json(name: str, obj: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


def write_artifact_atomic(
    path: Path,
    content: bytes | str,
) -> str:
    """Pass 043: Atomic artifact write (INV-Q1 prerequisite).

    Writes to a .tmp file first, then renames to the final path.
    os.replace() is atomic on Linux (POSIX rename) and best-effort on Windows
    NTFS (atomic within the same volume). Returns the sha256 hex of the content.

    Callers must separately set artifact.write_state = 'committed' in the DB
    after this succeeds to satisfy INV-Q1.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    raw: bytes = content if isinstance(content, bytes) else content.encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    os.replace(str(tmp), str(path))  # atomic on POSIX; best-effort on Windows NTFS
    return sha


def mark_artifact_committed(
    db: Any,
    run_id: str,
    artifact_type: str,
    storage_uri: str,
    sha256: str,
    byte_count: int,
) -> None:
    """Pass 043: Upsert an artifact row and set write_state='committed'.

    This is the companion call to write_artifact_atomic. Call it immediately
    after the atomic rename succeeds. Until this call completes, mark_succeeded
    will refuse to promote the run to succeeded (INV-Q1).

    Accepts a SQLAlchemy Session (db) or None (no-op for eval paths without DB).
    """
    if db is None:
        return
    from packages.db.models import Artifact, _uuid
    existing = (
        db.query(Artifact)
        .filter(Artifact.run_id == run_id, Artifact.artifact_type == artifact_type)
        .first()
    )
    if existing is not None:
        existing.storage_uri = storage_uri
        existing.sha256 = sha256
        existing.bytes = byte_count
        existing.write_state = "committed"
    else:
        db.add(Artifact(
            id=_uuid(),
            run_id=run_id,
            artifact_type=artifact_type,
            storage_uri=storage_uri,
            sha256=sha256,
            bytes=byte_count,
            write_state="committed",
        ))
    db.flush()


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
    # Pass 40: Strip INTERNAL-only fields from trajectory markers for MEDIATION.
    # run_metadata is not in the allowlist so it's already excluded above.
    traj = safe_ext.get("leverage_trajectory")
    if isinstance(traj, dict):
        raw_markers = traj.get("markers") or []
        safe_ext["leverage_trajectory"] = {
            **traj,
            "markers": [
                {"date": m.get("date"), "level": m.get("level"), "kind": m.get("kind")}
                for m in raw_markers
            ],
        }
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
