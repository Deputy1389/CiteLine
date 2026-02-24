from __future__ import annotations
from datetime import date
import re
from apps.worker.steps.events.report_quality import date_sanity, sanitize_for_report
from packages.shared.models import Event, Provider

def projection_date_display(event: Event) -> str:
    if not event.date or not event.date.value:
        return "Date not documented"
    value = event.date.value
    if isinstance(value, date):
        return f"{value.isoformat()} (time not documented)" if date_sanity(value) else "Date not documented"
    if not date_sanity(value.start):
        return "Date not documented"
    end_str = f" to {value.end}" if value.end and date_sanity(value.end) else ""
    return f"{value.start}{end_str} (time not documented)"

def iso_date_display(value: date) -> str:
    return f"{value.isoformat()} (time not documented)"

def get_provider_name(event: Event, providers: list[Provider]) -> str:
    if not event.provider_id:
        return "Unknown"
    for provider in providers:
        if provider.provider_id == event.provider_id:
            clean = sanitize_for_report(provider.normalized_name or provider.detected_name_raw)
            if not clean:
                return "Unknown"
            if provider.confidence < 60:
                return "Unknown"
            low_clean = clean.lower()
            if any(token in low_clean for token in ("medical record summary", "stress test", "chronology eval", "sample 172", "pdf", "page")):
                return "Unknown"
            if "radiology" in low_clean and event.event_type.value != "imaging_study":
                return "Unknown"
            if re.search(r"[a-f0-9]{8,}", low_clean):
                return "Unknown"
            return clean
    return "Unknown"

def get_citation_display(event: Event, page_map: dict[int, tuple[str, int]] | None) -> str:
    pages = sorted(set(event.source_page_numbers))
    if not pages:
        if event.citation_ids:
            return f"record refs: {', '.join(sorted(set(event.citation_ids))[:3])}"
        return ""
    refs: list[str] = []
    for page_number in pages[:5]:
        if page_map and page_number in page_map:
            filename, local_page = page_map[page_number]
            refs.append(f"{filename} p. {local_page}")
        else:
            refs.append(f"p. {page_number}")
    return ", ".join(refs)

def infer_page_patient_labels(page_text_by_number: dict[int, str] | None) -> dict[int, str]:
    if not page_text_by_number:
        return {}
    labels: dict[int, str] = {}
    synthea_name_re = re.compile(r"\b([A-Z][a-z]+[0-9]+)\s+([A-Z][A-Za-z'`-]+[0-9]+)\b")
    patient_name_re = re.compile(r"(?im)\b(?:patient name|name)\s*:\s*([A-Z][a-z]+(?:[ 	]+[A-Z][a-z]+){1,2})\b")
    for page_number, text in page_text_by_number.items():
        if not text:
            continue
        m = synthea_name_re.search(text)
        if m:
            labels[page_number] = f"{m.group(1)} {m.group(2)}"
            continue
        m2 = patient_name_re.search(text)
        if m2:
            labels[page_number] = m2.group(1).strip()
    if not labels:
        return labels

    filled: dict[int, str] = {}
    sorted_pages = sorted(page_text_by_number.keys())
    last_label: str | None = None
    for page_number in sorted_pages:
        if page_number in labels:
            last_label = labels[page_number]
        if last_label:
            filled[page_number] = last_label

    first_labeled_page = min(labels.keys())
    first_label = labels[first_labeled_page]
    for page_number in sorted_pages:
        if page_number < first_labeled_page:
            filled[page_number] = first_label

    filled.update(labels)
    return filled

def get_event_patient_label(event: Event, page_patient_labels: dict[int, str] | None) -> str:
    if not page_patient_labels:
        return "Unknown Patient"
    counts: dict[str, int] = {}
    for page_number in set(event.source_page_numbers):
        label = page_patient_labels.get(page_number)
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    if not counts:
        return "Unknown Patient"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
