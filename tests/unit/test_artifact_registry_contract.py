from __future__ import annotations

import re
from pathlib import Path

from packages.shared.artifacts import (
    ARTIFACT_EXTENSION_MAP,
    REQUIRED_PIPELINE_ARTIFACT_TYPES,
    VALID_DOWNLOAD_ARTIFACT_TYPES,
    missing_required_types,
)


def test_required_pipeline_types_are_downloadable():
    missing = [atype for atype in REQUIRED_PIPELINE_ARTIFACT_TYPES if atype not in VALID_DOWNLOAD_ARTIFACT_TYPES]
    assert not missing, f"Required artifact types missing from download registry: {missing}"


def test_artifact_extensions_defined_for_required_types():
    missing = [atype for atype in REQUIRED_PIPELINE_ARTIFACT_TYPES if atype not in ARTIFACT_EXTENSION_MAP]
    assert not missing, f"Required artifact types missing extension mapping: {missing}"


def test_ui_artifact_links_match_registry_subset():
    src = Path("apps/ui/src/artifacts.ts").read_text(encoding="utf-8")
    kv_pairs = dict(re.findall(r"([A-Z_]+):\s*['\"]([^'\"]+)['\"]", src))
    order_keys = re.findall(r"ARTIFACT_TYPES\.([A-Z_]+)", src.split("RUN_ARTIFACT_LINK_ORDER", 1)[1])

    ui_types = [kv_pairs[k] for k in order_keys]
    for atype in ui_types:
        assert atype in VALID_DOWNLOAD_ARTIFACT_TYPES, f"UI artifact type not downloadable: {atype}"

    # Ensure key workflow links remain present.
    assert "missing_records_csv" in ui_types
    assert "missing_record_requests_md" in ui_types

    # UI list is intentionally a subset of full registry.
    assert missing_required_types(ui_types)
