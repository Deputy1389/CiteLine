from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def write_artifact_json(name: str, obj: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


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

