from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from apps.worker.project.chronology import build_chronology_projection
from apps.worker.steps.step15_missing_records import choose_care_window, detect_missing_records
from apps.worker.lib.noise_filter import is_noise_span
from packages.shared.models import (
    DateKind,
    DateSource,
    EvidenceGraph,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Provider,
    ProviderType,
)


def _evt(event_id: str, d: date, text: str, et: EventType = EventType.OFFICE_VISIT, provider_id: str = "p1") -> Event:
    return Event(
        event_id=event_id,
        provider_id=provider_id,
        event_type=et,
        date=EventDate(kind=DateKind.SINGLE, value=d, source=DateSource.TIER1),
        facts=[Fact(text=text, kind=FactKind.OTHER, verbatim=True)],
        confidence=80,
        flags=[],
        citation_ids=["c1"],
        source_page_numbers=[1],
    )


def test_noise_classifier_flags_known_garbage():
    assert is_noise_span("Pain Assessment: Product main couple design") is True


def test_selection_meta_counts_are_consistent():
    events = [
        _evt(f"e{i}", date(2025, 1, 1), "Assessment: cervical radiculopathy with persistent pain.", EventType.OFFICE_VISIT)
        for i in range(30)
    ]
    providers = [
        Provider(
            provider_id="p1",
            detected_name_raw="Clinic",
            normalized_name="Clinic",
            provider_type=ProviderType.HOSPITAL,
            confidence=90,
        )
    ]
    meta = {}
    proj = build_chronology_projection(events, providers, selection_meta=meta)
    assert proj.entries
    assert len(meta["kept_ids"]) <= len(meta["candidates_after_backfill_ids"])
    assert len(meta["final_ids"]) <= len(meta["candidates_after_backfill_ids"])


def test_care_window_clamps_future_metadata_date():
    e1 = _evt("e1", date(2025, 1, 1), "Emergency visit with diagnosis and treatment.")
    e2 = _evt("e2", date(2025, 3, 1), "Follow-up visit with assessment and plan.")
    noisy_future = _evt("e3", date(2026, 4, 25), "Fax cover sheet product main couple design generated on 2026-04-25.")
    start, end = choose_care_window([e1, e2, noisy_future])
    assert start == date(2025, 1, 1)
    assert end == date(2025, 3, 1)


def test_missing_records_uses_care_window_end():
    e1 = _evt("e1", date(2025, 1, 1), "Emergency visit with diagnosis and treatment.")
    e2 = _evt("e2", date(2025, 3, 1), "Follow-up visit with assessment and plan.")
    noisy_future = _evt("e3", date(2026, 4, 25), "Fax cover sheet product main couple design generated on 2026-04-25.")
    graph = EvidenceGraph(events=[e1, e2, noisy_future], providers=[])
    out = detect_missing_records(graph, [])
    assert out["ruleset"]["care_window_end"] == "2025-03-01"
    assert all(g["end_date"] <= "2025-03-01" for g in out["gaps"])
