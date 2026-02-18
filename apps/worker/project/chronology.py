from __future__ import annotations

from datetime import date, datetime, timezone
import re
import hashlib
from collections import defaultdict

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
            low_clean = clean.lower()
            # Guard against document-title / run-label contamination in provider field.
            if any(
                token in low_clean
                for token in (
                    "medical record summary",
                    "stress test",
                    "chronology eval",
                    "sample 172",
                    "pdf",
                    "page",
                )
            ):
                return "Unknown"
            # Guard against cross-cluster radiology attribution leakage.
            if "radiology" in low_clean and event.event_type.value != "imaging_study":
                return "Unknown"
            if re.search(r"[a-f0-9]{8,}", low_clean):
                return "Unknown"
            return clean
    return "Unknown"


def _citation_display(event: Event, page_map: dict[int, tuple[str, int]] | None) -> str:
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
    patient_name_re = re.compile(r"(?im)\b(?:patient name|name)\s*:\s*([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,2})\b")
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

    # Propagate labels forward across pages so one header page can label subsequent pages.
    filled: dict[int, str] = {}
    sorted_pages = sorted(page_text_by_number.keys())
    last_label: str | None = None
    for page_number in sorted_pages:
        if page_number in labels:
            last_label = labels[page_number]
        if last_label:
            filled[page_number] = last_label

    # Backfill the initial gap from the first detected label to preceding pages.
    first_labeled_page = min(labels.keys())
    first_label = labels[first_labeled_page]
    for page_number in sorted_pages:
        if page_number < first_labeled_page:
            filled[page_number] = first_label

    # Keep direct detections authoritative.
    filled.update(labels)
    return filled


def _event_patient_label(event: Event, page_patient_labels: dict[int, str] | None) -> str:
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


def _is_vitals_heavy(text: str) -> bool:
    low = text.lower()
    vital_markers = [
        "body height",
        "body weight",
        "bmi",
        "blood pressure",
        "heart rate",
        "respiratory rate",
        "pain severity",
        "head occipital-frontal circumference",
    ]
    return sum(1 for marker in vital_markers if marker in low) >= 2


def _is_high_value_event(event: Event, joined_raw: str) -> bool:
    ext = event.extensions or {}
    sev = ext.get("severity_score")
    if isinstance(sev, int) and sev >= 55:
        return True

    low = joined_raw.lower()
    concept_hit = bool(procedure_canonicalization(joined_raw) or injury_canonicalization(joined_raw))
    if concept_hit:
        return True

    high_priority_types = {
        "er_visit",
        "hospital_admission",
        "hospital_discharge",
        "discharge",
        "procedure",
        "imaging_study",
        "inpatient_daily_note",
        "lab_result",
    }
    if event.event_type.value in high_priority_types:
        if event.event_type.value == "imaging_study":
            return bool(re.search(r"\b(impression|x-?ray|ct|mri|ultrasound|angiogram|fracture|tear|lesion)\b", low))
        return True

    severe_signal = bool(
        re.search(
            r"\b(phq-?9|depression|suicid|homeless|skilled nursing|emergency room|er visit|admission|discharge|opioid|hydrocodone|oxycodone|codeine)\b",
            low,
        )
    )
    if severe_signal:
        return True

    if _is_vitals_heavy(joined_raw):
        return False

    meaningful_clinic_signal = bool(
        re.search(
            r"\b(diagnosis|assessment|impression|fracture|infection|tear|follow-?up|medication|prescribed|therapy|plan|disposition|discharge)\b",
            low,
        )
    )
    questionnaire_only = bool(
        re.search(r"\b(phq-?9|gad-?7|pain interference|questionnaire|survey score|score)\b", low)
    ) and not bool(
        re.search(r"\b(admission|discharge|diagnosis|impression|procedure|surgery|infection|fracture|tear)\b", low)
    )
    if questionnaire_only and not severe_signal:
        return False
    if event.event_type.value in {"office_visit", "pt_visit", "inpatient_daily_note"} and meaningful_clinic_signal:
        return True

    if event.event_type.value in {"office_visit", "pt_visit", "inpatient_daily_note"} and re.search(
        r"\b(admission|discharge|assessment|impression|diagnosis|procedure|surgery|infection|fracture|tear|medication|started|stopped|increased|decreased|switched|plan|disposition|hospice|snf)\b",
        low,
    ):
        return True

    return False


def _parse_fact_dates(text: str) -> list[date]:
    if not text:
        return []
    out: list[date] = []
    for m in re.finditer(r"\b(20\d{2}|19\d{2})-([01]\d)-([0-3]\d)(?:\b|T)", text):
        yy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            out.append(date(yy, mm, dd))
        except ValueError:
            pass
    for m in re.finditer(r"\b([01]?\d)/([0-3]?\d)/(20\d{2}|19\d{2})\b", text):
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            out.append(date(yy, mm, dd))
        except ValueError:
            pass
    return [d for d in out if date_sanity(d)]


def _fact_temporally_consistent(fact_text: str, target_date: date | None) -> bool:
    if target_date is None:
        return True
    fact_dates = _parse_fact_dates(fact_text)
    if not fact_dates:
        return True
    # Reject the fact only when all embedded dates are far from the event date.
    return any(abs((fd - target_date).days) <= 30 for fd in fact_dates)


def _strip_conflicting_timestamps(fact_text: str, target_date: date | None) -> str:
    if target_date is None:
        return fact_text
    cleaned = fact_text
    for m in re.finditer(r"\b(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}Z\b", fact_text):
        try:
            ts_date = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if abs((ts_date - target_date).days) > 1:
            cleaned = cleaned.replace(m.group(0), "")
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _event_type_display(event: Event) -> str:
    mapping = {
        "hospital_admission": "Hospital Admission",
        "hospital_discharge": "Hospital Discharge",
        "er_visit": "Emergency Visit",
        "inpatient_daily_note": "Inpatient Progress",
        "office_visit": "Follow-Up Visit",
        "pt_visit": "Therapy Visit",
        "imaging_study": "Imaging Study",
        "procedure": "Procedure/Surgery",
        "lab_result": "Lab Result",
        "discharge": "Discharge",
    }
    key = event.event_type.value
    return mapping.get(key, key.replace("_", " ").title())


def _classify_projection_entry(entry: ChronologyProjectionEntry) -> str:
    et = (entry.event_type_display or "").lower()
    facts = " ".join(entry.facts).lower()
    if "admission" in et:
        return "inpatient"
    if "discharge" in et:
        return "discharge_transfer"
    if "emergency" in et or "er visit" in et or re.search(r"\bemergency room|ed visit\b", facts):
        return "ed_visit"
    if "procedure" in et or "surgery" in et:
        return "surgery_procedure"
    if "imaging" in et:
        return "imaging_impression"
    if "therapy" in et:
        return "therapy"
    if "lab" in et:
        return "labs"
    if re.search(r"\b(phq-?9|gad-?7|questionnaire|survey score|promis|pain interference)\b", facts):
        return "questionnaire"
    if re.search(
        r"\b(body height|body weight|blood pressure|respiratory rate|heart rate|temperature|bmi|weight percentile)\b",
        facts,
    ):
        return "vitals"
    if re.search(r"\b(intake|demographic|insurance|education|income|tobacco status)\b", facts):
        return "admin"
    if "follow-up visit" in et or "inpatient progress" in et:
        return "clinic"
    return "other"


def _projection_entry_score(entry: ChronologyProjectionEntry) -> int:
    event_class = _classify_projection_entry(entry)
    base = {
        "inpatient": 90,
        "discharge_transfer": 90,
        "ed_visit": 85,
        "surgery_procedure": 85,
        "imaging_impression": 75,
        "therapy": 55,
        "clinic": 35,
        "labs": 30,
        "questionnaire": 10,
        "vitals": 10,
        "admin": 0,
        "other": 20,
    }[event_class]
    facts = " ".join(entry.facts).lower()
    severe_score = False
    for m in re.finditer(r"\b(phq-?9|gad-?7|pain(?:\s+severity|\s+score)?)\s*[:=]?\s*(\d{1,2})\b", facts):
        try:
            if int(m.group(2)) >= 15:
                severe_score = True
                break
        except ValueError:
            continue
    if re.search(r"\b(disposition|discharged|skilled nursing|snf|hospice|return to work|work restriction|follow-?up)\b", facts):
        base += 15
    if re.search(r"\b(new|newly|started|initiated|stopped|discontinued|increased|decreased|switched|changed to)\b", facts):
        base += 15
    if severe_score:
        base += 10
    if re.search(
        r"\b(left|right|bilateral)\b.*\b(fracture|tear|injury|dislocation|infection|pain|wound)\b|\b(fracture|tear|injury|dislocation|infection|pain|wound)\b.*\b(left|right|bilateral)\b",
        facts,
    ):
        base += 10
    if event_class == "labs":
        if re.search(r"\b(critical|panic|high-risk|abnormal|elevated)\b", facts):
            base += 20
        else:
            base -= 10
    if event_class == "clinic" and not re.search(
        r"\b(assessment|impression|diagnosis|procedure|surgery|infection|fracture|tear|medication|started|stopped|increased|decreased|switched|plan|disposition|hospice|snf|admission|discharge)\b",
        facts,
    ):
        base -= 20
    if re.search(r"\b(tobacco status|never smoked|weight percentile|body weight|body height|blood pressure)\b", facts):
        base -= 20
    if re.search(r"\bclinical follow-?up documenting continuity, symptoms, and treatment response\b", facts):
        base -= 30
    if not (entry.citation_display or "").strip():
        base -= 15
    return max(0, min(100, base))


def _apply_timeline_selection(entries: list[ChronologyProjectionEntry]) -> list[ChronologyProjectionEntry]:
    if not entries:
        return entries
    grouped: dict[str, list[ChronologyProjectionEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.patient_label].append(entry)

    selected: list[ChronologyProjectionEntry] = []
    for patient_label in sorted(grouped.keys()):
        rows = grouped[patient_label]
        scored: list[tuple[int, str, ChronologyProjectionEntry]] = []
        seen_payload: set[tuple[str, str, str]] = set()
        for row in rows:
            event_class = _classify_projection_entry(row)
            score = _projection_entry_score(row)
            dedupe_key = (
                row.date_display,
                event_class,
                " ".join(f.strip().lower() for f in row.facts[:2]),
            )
            if dedupe_key in seen_payload:
                score = max(0, score - 20)
            else:
                seen_payload.add(dedupe_key)
            row.confidence = max(0, min(100, score))
            row.event_type_display = row.event_type_display
            scored.append((score, event_class, row))

        main = [(s, c, r) for (s, c, r) in scored if s >= 40]
        appendix = [(s, c, r) for (s, c, r) in scored if s < 40]
        strict_main: list[tuple[int, str, ChronologyProjectionEntry]] = []
        for item in main:
            score, cls, row = item
            facts_blob = " ".join(row.facts).lower()
            if cls == "clinic" and score < 55:
                appendix.append(item)
                continue
            if cls == "labs" and score < 45:
                appendix.append(item)
                continue
            if cls in {"other", "admin"} and score < 60:
                appendix.append(item)
                continue
            if re.search(r"\b(tobacco status|never smoked|weight percentile)\b", facts_blob):
                appendix.append(item)
                continue
            strict_main.append(item)
        main = strict_main

        main.sort(key=lambda item: (item[2].date_display, -item[0], item[2].event_id))
        if main:
            max_vq = max(1, int(len(main) * 0.10))
            max_admin = max(0, int(len(main) * 0.05))
            max_labs = max(1, int(len(main) * 0.20))
            kept: list[tuple[int, str, ChronologyProjectionEntry]] = []
            vq_count = 0
            admin_count = 0
            lab_count = 0
            for item in main:
                score, cls, row = item
                if cls in {"vitals", "questionnaire"}:
                    if vq_count >= max_vq:
                        appendix.append(item)
                        continue
                    vq_count += 1
                if cls == "admin":
                    if admin_count >= max_admin:
                        appendix.append(item)
                        continue
                    admin_count += 1
                if cls == "labs":
                    if score < 45:
                        appendix.append(item)
                        continue
                    if lab_count >= max_labs:
                        appendix.append(item)
                        continue
                    if not re.search(r"\b(h|l|high|low|critical|panic|elevated|depressed|abnormal|>|<)\b", " ".join(row.facts).lower()):
                        appendix.append(item)
                        continue
                    lab_count += 1
                kept.append(item)
            main = kept

        high_value_candidates = sum(1 for _, cls, _ in scored if cls not in {"vitals", "questionnaire", "admin"})
        coverage_floor = max(8, int(round(0.15 * max(high_value_candidates, 1))))
        coverage_floor = min(coverage_floor, len(scored))
        appendix.sort(key=lambda item: (-item[0], item[2].date_display, item[2].event_id))
        while len(main) < coverage_floor:
            promoted = None
            for idx, candidate in enumerate(appendix):
                score, cls, row = candidate
                if cls in {"vitals", "questionnaire", "admin"}:
                    continue
                if cls == "labs" and (score < 45 or not re.search(r"\b(h|l|high|low|critical|panic|elevated|depressed|abnormal|>|<)\b", " ".join(row.facts).lower())):
                    continue
                promoted = appendix.pop(idx)
                break
            if promoted is None:
                break
            main.append(promoted)

        main.sort(key=lambda item: (item[2].date_display, -item[0], item[2].event_id))
        selected.extend([row for _, _, row in main])
    return selected


def _merge_projection_entries(entries: list[ChronologyProjectionEntry], select_timeline: bool = True) -> list[ChronologyProjectionEntry]:
    grouped: dict[tuple[str, str], list[ChronologyProjectionEntry]] = {}
    for entry in entries:
        key = (entry.patient_label, entry.date_display)
        grouped.setdefault(key, []).append(entry)

    merged: list[ChronologyProjectionEntry] = []
    type_rank = {
        "Hospital Admission": 1,
        "Emergency Visit": 2,
        "Procedure/Surgery": 3,
        "Imaging Study": 4,
        "Hospital Discharge": 5,
        "Discharge": 6,
        "Inpatient Progress": 7,
        "Follow-Up Visit": 8,
        "Therapy Visit": 9,
        "Lab Result": 10,
    }
    for key in sorted(grouped.keys(), key=lambda k: (k[0], k[1])):
        group = grouped[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        all_ids = sorted({g.event_id for g in group})
        event_id = hashlib.sha1("|".join(all_ids).encode("utf-8")).hexdigest()[:16]
        facts: list[str] = []
        seen_facts: set[str] = set()
        citations: list[str] = []
        provider_counts: dict[str, int] = {}
        event_types: list[str] = []
        for g in group:
            provider_counts[g.provider_display] = provider_counts.get(g.provider_display, 0) + 1
            event_types.append(g.event_type_display)
            for fact in g.facts:
                norm = fact.strip().lower()
                if norm and norm not in seen_facts:
                    facts.append(fact)
                    seen_facts.add(norm)
                if len(facts) >= 4:
                    break
            if g.citation_display:
                citations.extend([part.strip() for part in g.citation_display.split(",") if part.strip()])
        merged_citations = ", ".join(sorted(set(citations))[:6])
        provider_display = sorted(provider_counts.items(), key=lambda item: (item[0] == "Unknown", -item[1], item[0]))[0][0]
        event_type_display = sorted(event_types, key=lambda et: (type_rank.get(et, 99), et))[0]
        merged.append(
            ChronologyProjectionEntry(
                event_id=event_id,
                date_display=key[1],
                provider_display=provider_display,
                event_type_display=event_type_display,
                patient_label=key[0],
                facts=facts[:4],
                citation_display=merged_citations,
                confidence=max(g.confidence for g in group),
            )
        )

    def _entry_date_key(entry: ChronologyProjectionEntry) -> tuple[int, str]:
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", entry.date_display)
        if not m:
            return (99, "9999-12-31")
        return (0, m.group(1))

    if select_timeline:
        merged = _apply_timeline_selection(merged)
    return sorted(merged, key=lambda e: (e.patient_label, _entry_date_key(e), e.event_id))


def build_chronology_projection(
    events: list[Event],
    providers: list[Provider],
    page_map: dict[int, tuple[str, int]] | None = None,
    page_patient_labels: dict[int, str] | None = None,
    page_text_by_number: dict[int, str] | None = None,
    debug_sink: list[dict] | None = None,
    select_timeline: bool = True,
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
            inferred_from_provider = None
        else:
            pages = sorted(set(event.source_page_numbers))
            if not pages:
                inferred_from_provider = None
            else:
                candidates: list[tuple[int, date]] = []
                for source_page, source_date in provider_dated_pages[event.provider_id]:
                    min_dist = min(abs(p - source_page) for p in pages)
                    if min_dist <= 2:
                        candidates.append((min_dist, source_date))
                if not candidates:
                    inferred_from_provider = None
                else:
                    candidates.sort(key=lambda item: (item[0], item[1].isoformat()))
                    inferred_from_provider = candidates[0][1]
        if inferred_from_provider is not None:
            return inferred_from_provider

        if not page_text_by_number:
            return None
        page_dates: list[date] = []
        for p in sorted(set(event.source_page_numbers)):
            text = page_text_by_number.get(p, "")
            if not text:
                continue
            for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)(?:\b|T)", text):
                yy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    d = date(yy, mm, dd)
                except ValueError:
                    continue
                if date_sanity(d):
                    page_dates.append(d)
            for m in re.finditer(r"\b([01]?\d)/([0-3]?\d)/(19[7-9]\d|20\d{2})\b", text):
                mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    d = date(yy, mm, dd)
                except ValueError:
                    continue
                if date_sanity(d):
                    page_dates.append(d)
        if not page_dates:
            return None
        return sorted(page_dates)[0]

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
        high_value = _is_high_value_event(event, joined_raw)
        effective_date: date | None = None
        if event.date and event.date.value and isinstance(event.date.value, date):
            effective_date = event.date.value if date_sanity(event.date.value) else None
        elif inferred_date:
            effective_date = inferred_date

        for fact in event.facts:
            if not is_reportable_fact(fact.text):
                continue
            cleaned = sanitize_for_report(fact.text)
            low_cleaned = cleaned.lower()
            if "labs found:" in low_cleaned and not re.search(
                r"\b(h|l|high|low|critical|panic|elevated|depressed|abnormal|>|<)\b",
                low_cleaned,
            ):
                continue
            if re.search(
                r"\b(tobacco status|never smoked|smokeless tobacco|weight percentile|body height|body weight|head occipital-frontal circumference)\b",
                low_cleaned,
            ):
                continue
            if not _fact_temporally_consistent(cleaned, effective_date):
                if debug_sink is not None:
                    debug_sink.append({"event_id": event.event_id, "reason": "fact_date_mismatch", "provider_id": event.provider_id})
                continue
            cleaned = _strip_conflicting_timestamps(cleaned, effective_date)
            if len(cleaned) > 280:
                cleaned = cleaned[:280] + "..."
            if _is_vitals_heavy(cleaned):
                continue
            low_fact = cleaned.lower()
            # Keep questionnaire/scores out of the main timeline unless clinically severe.
            if re.search(r"\b(phq-?9|gad-?7|pain interference|questionnaire|survey score|score)\b", low_fact):
                severe_score = False
                m = re.search(r"\b(phq-?9|gad-?7)\s*[:=]?\s*(\d{1,2})\b", low_fact)
                if m and int(m.group(2)) >= 15:
                    severe_score = True
                if not severe_score:
                    continue
            facts.append(cleaned)
            if len(facts) >= 3:
                break
        # Minimum substance threshold for client timeline.
        if not high_value or not facts:
            if debug_sink is not None:
                debug_sink.append({"event_id": event.event_id, "reason": "low_substance", "provider_id": event.provider_id})
            continue

        if event.date and event.date.value:
            date_display = _projection_date_display(event)
        elif inferred_date:
            date_display = _iso_date_display(inferred_date)
        else:
            date_display = "Date not documented"

        citation_display = _citation_display(event, page_map)
        if not citation_display:
            if debug_sink is not None:
                debug_sink.append({"event_id": event.event_id, "reason": "no_citation", "provider_id": event.provider_id})
            continue

        entries.append(
            ChronologyProjectionEntry(
                event_id=event.event_id,
                date_display=date_display,
                provider_display=_provider_name(event, providers),
                event_type_display=_event_type_display(event),
                patient_label=_event_patient_label(event, page_patient_labels),
                facts=facts,
                citation_display=citation_display,
                confidence=event.confidence,
            )
        )
    merged_entries = _merge_projection_entries(entries, select_timeline=select_timeline)
    if not merged_entries:
        fallback: list[ChronologyProjectionEntry] = []
        for event in sorted_events:
            joined = " ".join((f.text or "") for f in event.facts).lower()
            if event.event_type.value == "lab_result" and not re.search(
                r"\b(h|l|high|low|critical|panic|elevated|depressed|abnormal|>|<)\b",
                joined,
            ):
                continue
            facts: list[str] = []
            for fact in event.facts:
                if not is_reportable_fact(fact.text):
                    continue
                cleaned = sanitize_for_report(fact.text)
                if cleaned:
                    facts.append(cleaned[:220])
                if len(facts) >= 2:
                    break
            if not facts:
                continue
            if _is_vitals_heavy(" ".join(facts)):
                continue
            citation_display = _citation_display(event, page_map)
            if not citation_display:
                continue
            fallback.append(
                ChronologyProjectionEntry(
                    event_id=event.event_id,
                    date_display="Date not established from source records",
                    provider_display=_provider_name(event, providers),
                    event_type_display=_event_type_display(event),
                    patient_label=_event_patient_label(event, page_patient_labels),
                    facts=facts,
                    citation_display=citation_display,
                    confidence=event.confidence,
                )
            )
            if len(fallback) >= 3:
                break
        merged_entries = fallback
    return ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=merged_entries)
