"""
CSV rendering for chronology export.

Handles generation of CSV output from chronology projection.
Extracted from step12_export.py during refactor - behavior preserved exactly.
"""
from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.worker.project.models import ChronologyProjection
    from packages.shared.models import Event, Provider


def generate_csv_from_projection(projection: ChronologyProjection) -> bytes:
    """Generate CSV from chronology projection."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["event_id", "date", "provider", "type", "facts", "source"])
    for entry in projection.entries:
        writer.writerow(
            [
                entry.event_id,
                entry.date_display,
                entry.provider_display,
                entry.event_type_display,
                "; ".join(entry.facts),
                entry.citation_display,
            ]
        )
    return buf.getvalue().encode("utf-8")


def generate_csv(
    events: list[Event],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
    **kwargs,
) -> bytes:
    """Generate a CSV chronology with one row per event."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "event_id", "date", "provider", "type", "confidence",
        "facts", "source_files",
    ])

    from apps.worker.steps.export_render.common import (
        _date_str,
        _facts_text,
        _pages_ref,
        _provider_name,
    )
    for event in events:
        date_display = _date_str(event)
        writer.writerow([
            event.event_id,
            date_display,
            _provider_name(event, providers),
            event.event_type.value,
            event.confidence,
            _facts_text(event),
            _pages_ref(event, page_map),
        ])

    return buf.getvalue().encode("utf-8")
