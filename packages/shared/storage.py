"""
Local disk storage helpers for uploads and artifacts.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "C:/CiteLine/data"))
UPLOADS_DIR = DATA_DIR / "uploads"
ARTIFACTS_DIR = DATA_DIR / "artifacts"


def ensure_dirs() -> None:
    """Create data directories if they don't exist."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def sha256_bytes(data: bytes) -> str:
    """Compute sha256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def save_upload(source_document_id: str, file_bytes: bytes) -> Path:
    """Save uploaded PDF to local disk. Returns the file path."""
    ensure_dirs()
    path = UPLOADS_DIR / f"{source_document_id}.pdf"
    path.write_bytes(file_bytes)
    return path


def get_upload_path(source_document_id: str) -> Path:
    """Return the path to a previously-saved upload."""
    return UPLOADS_DIR / f"{source_document_id}.pdf"


def save_artifact(run_id: str, filename: str, data: bytes) -> Path:
    """Save a generated artifact (PDF/CSV/JSON) to the run's artifact dir."""
    ensure_dirs()
    run_dir = ARTIFACTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / filename
    path.write_bytes(data)
    return path


def get_artifact_dir(run_id: str) -> Path:
    """Return the artifact directory for a given run."""
    return ARTIFACTS_DIR / run_id


def get_artifact_path(run_id: str, filename: str) -> Path:
    """Return the full path to a specific artifact."""
    return ARTIFACTS_DIR / run_id / filename
