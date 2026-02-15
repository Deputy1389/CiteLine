"""
Validate pipeline output JSON against the PI Chronology MVP schema.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "pi-chronology-mvp.schema.json"
_schema_cache: dict | None = None


def _load_schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


def validate_output(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate *data* against the PI Chronology MVP JSON schema.
    Returns (is_valid, list_of_error_messages).
    """
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    messages = [f"{'→'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors]
    return (len(messages) == 0, messages)
