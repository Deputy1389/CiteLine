from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

from apps.worker.project.chronology import infer_page_patient_labels
from packages.shared.models import ArtifactRef, Citation, Event, Page
from packages.shared.storage import save_artifact


def _scope_id_from_label(label: str) -> str:
    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]
    return f"ps_{digest}"


def _direct_header_labels(pages: list[Page]) -> dict[int, str]:
    labels: dict[int, str] = {}
    synthea_name_re = re.compile(r"\b([A-Z][a-z]+[0-9]+)\s+([A-Z][A-Za-z'`-]+[0-9]+)\b")
    patient_name_re = re.compile(r"(?im)\b(?:patient name|name)\s*:\s*([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,2})\b")
    for page in pages:
        text = page.text or ""
        if not text:
            continue
        m = synthea_name_re.search(text)
        if m:
            labels[page.page_number] = f"{m.group(1)} {m.group(2)}"
            continue
        m2 = patient_name_re.search(text)
        if m2:
            labels[page.page_number] = m2.group(1).strip()
    return labels


def build_patient_partitions(pages: list[Page]) -> tuple[dict, dict[int, str]]:
    page_text_by_number = {p.page_number: (p.text or "") for p in pages}
    propagated_labels = infer_page_patient_labels(page_text_by_number)
    direct_labels = _direct_header_labels(pages)

    page_to_scope: dict[int, str] = {}
    pages_by_scope: dict[str, list[int]] = defaultdict(list)
    scope_label_map: dict[str, str] = {}
    for page_number in sorted(page_text_by_number.keys()):
        label = propagated_labels.get(page_number) or "Unknown Patient"
        scope_id = _scope_id_from_label(label)
        page_to_scope[page_number] = scope_id
        pages_by_scope[scope_id].append(page_number)
        scope_label_map[scope_id] = label

    partitions: list[dict] = []
    for scope_id in sorted(pages_by_scope.keys()):
        page_numbers = sorted(pages_by_scope[scope_id])
        direct_hits = sum(1 for p in page_numbers if p in direct_labels)
        confidence = int(round((direct_hits / len(page_numbers)) * 100)) if page_numbers else 0
        partitions.append(
            {
                "patient_scope_id": scope_id,
                "label": scope_label_map[scope_id],
                "page_start": page_numbers[0] if page_numbers else None,
                "page_end": page_numbers[-1] if page_numbers else None,
                "page_count": len(page_numbers),
                "page_numbers": page_numbers,
                "confidence": confidence,
            }
        )

    payload = {
        "version": "1.0",
        "partitions": partitions,
        "unassigned_pages": [],
        "total_pages": len(pages),
        "partition_count": len(partitions),
    }
    return payload, page_to_scope


def assign_patient_scope_to_events(events: list[Event], page_to_scope: dict[int, str]) -> None:
    for event in events:
        scope_counts: dict[str, int] = defaultdict(int)
        for page_number in event.source_page_numbers:
            scope = page_to_scope.get(page_number)
            if scope:
                scope_counts[scope] += 1
        event.extensions = dict(event.extensions or {})
        if not scope_counts:
            event.extensions["patient_scope_id"] = _scope_id_from_label("Unknown Patient")
            event.extensions["patient_scope_confidence"] = 0
            continue
        best = sorted(scope_counts.items(), key=lambda item: (-item[1], item[0]))[0]
        confidence = int(round((best[1] / max(1, len(event.source_page_numbers))) * 100))
        event.extensions["patient_scope_id"] = best[0]
        event.extensions["patient_scope_confidence"] = confidence


def enforce_event_patient_scope(
    events: list[Event],
    citations: list[Citation],
    page_to_scope: dict[int, str],
) -> None:
    by_citation_id = {c.citation_id: c for c in citations}
    for event in events:
        ext = event.extensions or {}
        event_scope = ext.get("patient_scope_id")
        if not event_scope:
            continue
        event.source_page_numbers = [
            p for p in event.source_page_numbers if page_to_scope.get(p) == event_scope
        ]
        kept_cids: list[str] = []
        for cid in event.citation_ids:
            cit = by_citation_id.get(cid)
            if not cit:
                continue
            if page_to_scope.get(cit.page_number) == event_scope:
                kept_cids.append(cid)
        event.citation_ids = sorted(set(kept_cids))


def validate_patient_scope_invariants(
    events: list[Event],
    citations: list[Citation],
    page_to_scope: dict[int, str],
) -> list[dict]:
    by_citation_id = {c.citation_id: c for c in citations}
    violations: list[dict] = []
    for event in events:
        scopes = {page_to_scope.get(p) for p in event.source_page_numbers if page_to_scope.get(p)}
        if len(scopes) > 1:
            violations.append(
                {
                    "event_id": event.event_id,
                    "type": "event_cross_scope_pages",
                    "scopes": sorted(scopes),
                }
            )
        event_scope = (event.extensions or {}).get("patient_scope_id")
        for citation_id in event.citation_ids:
            cit = by_citation_id.get(citation_id)
            if not cit:
                continue
            citation_scope = page_to_scope.get(cit.page_number)
            if event_scope and citation_scope and event_scope != citation_scope:
                violations.append(
                    {
                        "event_id": event.event_id,
                        "citation_id": citation_id,
                        "type": "event_citation_scope_mismatch",
                        "event_scope": event_scope,
                        "citation_scope": citation_scope,
                    }
                )
    return violations


def render_patient_partitions(run_id: str, payload: dict) -> ArtifactRef:
    json_bytes = json.dumps(payload, indent=2).encode("utf-8")
    path = save_artifact(run_id, "patient_partitions.json", json_bytes)
    sha = hashlib.sha256(json_bytes).hexdigest()
    return ArtifactRef(uri=str(path), sha256=sha, bytes=len(json_bytes))
