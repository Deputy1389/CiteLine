from __future__ import annotations

from datetime import date, datetime, timezone
import re

from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.events.report_quality import (
    date_sanity,
    injury_canonicalization,
    is_reportable_fact,
    procedure_canonicalization,
    sanitize_for_report,
    surgery_classifier_guard,
)
from packages.shared.models import Event, Provider


def _projection_date_display(event: Event) -> str:
    if not event.date or not event.date.value:
        return "Date not documented"
    value = event.date.value
    if isinstance(value, date):
        return f"{value.isoformat()} (time not documented)" if date_sanity(value) else "Date not documented"
    if not date_sanity(value.start):
        return "Date not documented"
    end_str = f" to {value.end}" if value.end and date_sanity(value.end) else ""
    return f"{value.start}{end_str} (time not documented)"


def _iso_date_display(value: date) -> str:
    return f"{value.isoformat()} (time not documented)"


def _provider_name(event: Event, providers: list[Provider]) -> str:
    if not event.provider_id:
        return "Unknown"
    for provider in providers:
        if provider.provider_id == event.provider_id:
            clean = sanitize_for_report(provider.normalized_name or provider.detected_name_raw)
            if not clean:
                return "Unknown"
            if provider.confidence < 70:
                return "Unknown"
            # Guard against cross-cluster radiology attribution leakage.
            if "radiology" in clean.lower() and event.event_type.value != "imaging_study":
                return "Unknown"
            if re.search(r"[a-f0-9]{8,}", clean.lower()):
                return "Unknown"
            return clean
    return "Unknown"


def _citation_display(event: Event, page_map: dict[int, tuple[str, int]] | None) -> str:
    pages = sorted(set(event.source_page_numbers))
    if not pages:
        return ""
    refs: list[str] = []
    for page_number in pages[:5]:
        if page_map and page_number in page_map:
            filename, local_page = page_map[page_number]
            refs.append(f"{filename} p. {local_page}")
        else:
            refs.append(f"p. {page_number}")
    return ", ".join(refs)


def build_chronology_projection(
    events: list[Event],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
    debug_sink: list[dict] | None = None,
) -> ChronologyProjection:
    entries: list[ChronologyProjectionEntry] = []
    sorted_events = sorted(events, key=lambda e: e.date.sort_key() if e.date else (99, "UNKNOWN"))

    provider_dated_pages: dict[str, list[tuple[int, date]]] = {}
    for event in sorted_events:
        if not event.provider_id or not event.date or not event.date.value:
            continue
        if isinstance(event.date.value, date) and date_sanity(event.date.value):
            pages = sorted(set(event.source_page_numbers))
            if not pages:
                continue
            provider_dated_pages.setdefault(event.provider_id, [])
            for page in pages:
                provider_dated_pages[event.provider_id].append((page, event.date.value))

    def infer_date(event: Event) -> date | None:
        if not event.provider_id or event.provider_id not in provider_dated_pages:
            return None
        pages = sorted(set(event.source_page_numbers))
        if not pages:
            return None
        candidates: list[tuple[int, date]] = []
        for source_page, source_date in provider_dated_pages[event.provider_id]:
            min_dist = min(abs(p - source_page) for p in pages)
            if min_dist <= 2:
                candidates.append((min_dist, source_date))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1].isoformat()))
        return candidates[0][1]

    for event in sorted_events:
        if not surgery_classifier_guard(event):
            if debug_sink is not None:
                debug_sink.append({"event_id": event.event_id, "reason": "surgery_guard", "provider_id": event.provider_id})
            continue
        inferred_date: date | None = None
        if not event.date or not event.date.value:
            inferred_date = infer_date(event)
            if inferred_date is None:
                if debug_sink is not None:
                    debug_sink.append({"event_id": event.event_id, "reason": "undated_no_inference", "provider_id": event.provider_id})
                continue

        facts: list[str] = []
        joined_raw = " ".join(f.text for f in event.facts if f.text)
        high_value = bool(procedure_canonicalization(joined_raw) or injury_canonicalization(joined_raw))
        if not high_value:
            high_value = bool(re.search(r"\b(impression|x-?ray|ct|mri|ultrasound|angiogram|fracture|tear|infection)\b", joined_raw, re.IGNORECASE))
        for fact in event.facts:
            if not is_reportable_fact(fact.text):
                continue
            cleaned = sanitize_for_report(fact.text)
            if len(cleaned) > 280:
                cleaned = cleaned[:280] + "..."
            facts.append(cleaned)
            if len(facts) >= 3:
                break
        # Minimum substance threshold for client timeline.
        if not facts or (not high_value and len(facts) < 2):
            if debug_sink is not None:
                debug_sink.append({"event_id": event.event_id, "reason": "low_substance", "provider_id": event.provider_id})
            continue

        if event.date and event.date.value:
            date_display = _projection_date_display(event)
        elif inferred_date:
            date_display = _iso_date_display(inferred_date)
        else:
            date_display = "Date not documented"

        entries.append(
            ChronologyProjectionEntry(
                event_id=event.event_id,
                date_display=date_display,
                provider_display=_provider_name(event, providers),
                event_type_display=event.event_type.value.replace("_", " ").title(),
                facts=facts,
                citation_display=_citation_display(event, page_map),
                confidence=event.confidence,
            )
        )
    return ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=entries)
