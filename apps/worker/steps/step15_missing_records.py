"""
Step 15 — Missing Record Detection (Phase 3).

Deterministic coverage analysis that detects gaps in medical records based on the EvidenceGraph.
This implementation is purely graph-derived and does not use NLP or external APIs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Set
import re

from packages.shared.models import ArtifactRef, EvidenceGraph, MissingRecordsExtension
from packages.shared.storage import save_artifact
from apps.worker.lib.noise_filter import is_noise_span


CARE_EVENT_TYPES = {
    "er_visit",
    "hospital_admission",
    "hospital_discharge",
    "discharge",
    "procedure",
    "imaging_study",
    "office_visit",
    "pt_visit",
    "inpatient_daily_note",
    "lab_result",
}
ACUTE_EVENT_TYPES = {"hospital_admission", "procedure"}


def _patient_scope_id(event) -> str:
    ext = event.extensions or {}
    scope = ext.get("patient_scope_id")
    return str(scope) if scope else "ps_default"


def _fact_blob(event) -> str:
    return " ".join((f.text or "") for f in event.facts).lower()


def _event_substance_score(event) -> int:
    text = _fact_blob(event)
    score = 0
    if re.search(r"\b(admission|discharge|procedure|surgery|impression|diagnosis|assessment|emergency|ed)\b", text):
        score += 3
    if re.search(r"\b(fracture|tear|infection|radiculopathy|debridement|orif|mri|ct|x-?ray)\b", text):
        score += 2
    if re.search(r"\b(started|stopped|switched|increased|decreased|prescribed)\b", text):
        score += 1
    if _is_vitals_only(text):
        score -= 2
    return score


def choose_care_window(events: list) -> tuple[Optional[date], Optional[date]]:
    dated: list[tuple[date, Any]] = []
    today = datetime.now(timezone.utc).date()
    for event in events:
        if not getattr(event, "date", None):
            continue
        d = event.date.sort_date()
        if d.year <= 1900:
            continue
        blob = _fact_blob(event)
        if d > (today + timedelta(days=7)) and not re.search(r"\b(appointment|scheduled|follow[- ]?up on)\b", blob):
            continue
        if is_noise_span(blob):
            continue
        if len(getattr(event, "citation_ids", []) or []) == 0 and len(getattr(event, "source_page_numbers", []) or []) == 0:
            continue
        event_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        if _event_substance_score(event) < 1 and event_type != "pt_visit":
            continue
        dated.append((d, event))
    if not dated:
        return None, None
    dated.sort(key=lambda t: t[0])
    start = dated[0][0]
    all_dates = [d for d, _ in dated]
    end = all_dates[-1]
    # Preserve full documented care windows for long-running treatment packets.
    if (end - start).days > 730:
        idx95 = int(0.95 * (len(all_dates) - 1))
        p95 = all_dates[idx95]
        high_value_tail = [d for d, e in dated if d > p95 and _event_substance_score(e) >= 2]
        end = max([p95] + high_value_tail) if high_value_tail else p95
    return start, end


def _is_vitals_only(text: str) -> bool:
    markers = (
        "body height",
        "body weight",
        "blood pressure",
        "respiratory rate",
        "heart rate",
        "temperature",
        "pulse",
        "spo2",
        "bmi",
    )
    return sum(1 for m in markers if m in text) >= 2 and not re.search(
        r"\b(admission|discharge|procedure|surgery|debridement|orif|infection|fracture|tear|mri|ct|x-?ray|ed|emergency)\b",
        text,
    )


def _is_care_event(event) -> bool:
    ext = event.extensions or {}
    if isinstance(ext.get("is_care_event"), bool):
        return bool(ext.get("is_care_event"))
    event_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
    if event_type not in CARE_EVENT_TYPES:
        return False
    text = _fact_blob(event)
    if is_noise_span(text):
        return False
    severe_signal = bool(
        re.search(
            r"\b(phq-?9|homeless|suicid|opioid|hydrocodone|oxycodone|admission|discharge|procedure|surgery|debridement|orif|infection|fracture|tear|ed|emergency)\b",
            text,
        )
    )
    if severe_signal:
        return True
    if event_type in {"er_visit", "hospital_admission", "hospital_discharge", "discharge", "procedure", "imaging_study"}:
        return True
    return not _is_vitals_only(text)


def _is_acute_event(event) -> bool:
    event_type = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
    if event_type in ACUTE_EVENT_TYPES:
        return True
    blob = _fact_blob(event)
    return bool(re.search(r"\b(hospice|skilled nursing|snf)\b", blob))


def detect_missing_records(
    evidence_graph: EvidenceGraph,
    providers_normalized: list[dict], # Provided for context, but we prioritize graph data
) -> dict:
    """
    Run missing-record detection based strictly on EvidenceGraph events.
    """
    # STEP 1 — Build deterministic visit date maps from EVENTS
    provider_visit_dates: dict[tuple[str, str], Set[date]] = {}
    global_visit_dates: dict[str, Set[date]] = {}
    care_start, care_end = choose_care_window(evidence_graph.events)

    # Mapping for provider display names
    provider_names: dict[str, str] = {
        p.provider_id: p.detected_name_raw for p in evidence_graph.providers
    }

    # Authoritative source of visit timing
    for event in evidence_graph.events:
        if not _is_care_event(event):
            continue
        if not event.date:
            continue
        
        visit_date = event.date.sort_date()
        # Skip unknown/placeholder dates (sort_date returns 1900-01-01 for unknown)
        if visit_date.year <= 1900:
            continue
        if care_start and visit_date < care_start:
            continue
        if care_end and visit_date > care_end:
            continue

        patient_scope_id = _patient_scope_id(event)
        if patient_scope_id == "ps_unknown":
            continue
        if patient_scope_id not in global_visit_dates:
            global_visit_dates[patient_scope_id] = set()
        global_visit_dates[patient_scope_id].add(visit_date)
        
        pid = event.provider_id
        if pid and pid != "unknown":
            key = (patient_scope_id, pid)
            if key not in provider_visit_dates:
                provider_visit_dates[key] = set()
            provider_visit_dates[key].add(visit_date)

    # Pre-sort events by sort_key for "latest/earliest" logic
    sorted_events_for_evidence = sorted(
        evidence_graph.events, 
        key=lambda e: e.date.sort_key() if e.date else (99, "UNKNOWN")
    )

    # Sort dates ascending
    sorted_global_dates_by_scope: dict[str, list[date]] = {
        scope: sorted(list(dates)) for scope, dates in global_visit_dates.items()
    }
    
    sorted_provider_dates: dict[tuple[str, str], list[date]] = {}
    for key, dates in provider_visit_dates.items():
        sorted_provider_dates[key] = sorted(list(dates))

    gaps = []

    # STEP 2 — Compute PROVIDER GAPS
    for key, visit_dates in sorted_provider_dates.items():
        patient_scope_id, pid = key
        if len(visit_dates) < 2:
            continue
        
        display_name = provider_names.get(pid, "Unknown Provider")

        for i in range(len(visit_dates) - 1):
            d1 = visit_dates[i]
            d2 = visit_dates[i+1]
            gap_days = (d2 - d1).days
            # Find boundary events for evidence
            # We need all events on these dates for this provider to get citations
            events_on_d1 = [e for e in sorted_events_for_evidence 
                            if _is_care_event(e)
                            and _patient_scope_id(e) == patient_scope_id
                            and e.provider_id == pid and e.date and e.date.sort_date() == d1]
            events_on_d2 = [e for e in sorted_events_for_evidence 
                            if _is_care_event(e)
                            and _patient_scope_id(e) == patient_scope_id
                            and e.provider_id == pid and e.date and e.date.sort_date() == d2]
            boundary_acute = bool((events_on_d1 and _is_acute_event(events_on_d1[-1])) or (events_on_d2 and _is_acute_event(events_on_d2[0])))
            min_days = 30
            if gap_days >= min_days:
                severity = "high" if gap_days >= 60 else "medium"
                
                # Stable hash for gap_id
                gap_seed = f"{patient_scope_id}{pid}{d1.isoformat()}{d2.isoformat()}provider_gap_v1"
                gap_id = hashlib.sha256(gap_seed.encode()).hexdigest()[:16]
                
                # latest event on start_date
                last_event = events_on_d1[-1] if events_on_d1 else None
                # earliest event on end_date
                next_event = events_on_d2[0] if events_on_d2 else None

                citation_ids = set()
                if last_event:
                    citation_ids.update(last_event.citation_ids)
                if next_event:
                    citation_ids.update(next_event.citation_ids)

                gaps.append({
                    "gap_id": gap_id,
                    "provider_id": pid,
                    "provider_display_name": display_name,
                    "patient_scope_id": patient_scope_id,
                    "start_date": d1.isoformat(),
                    "end_date": d2.isoformat(),
                    "gap_days": gap_days,
                    "severity": severity,
                    "rule_name": "provider_gap",
                    "rationale": "Post-acute follow-up gap" if boundary_acute else "No documented visits for provider during this period",
                    "evidence": {
                        "last_event_id": last_event.event_id if last_event else None,
                        "next_event_id": next_event.event_id if next_event else None,
                        "citation_ids": sorted(list(citation_ids))
                    },
                    "suggested_records_to_request": {
                        "provider_id": pid,
                        "patient_scope_id": patient_scope_id,
                        "from": (d1 + timedelta(days=1)).isoformat(),
                        "to": (d2 - timedelta(days=1)).isoformat(),
                        "type": "Medical records"
                    }
                })

    # STEP 3 — Compute GLOBAL GAPS (scoped per patient)
    for patient_scope_id, sorted_global_dates in sorted(sorted_global_dates_by_scope.items(), key=lambda item: item[0]):
        for i in range(len(sorted_global_dates) - 1):
            d1 = sorted_global_dates[i]
            d2 = sorted_global_dates[i+1]
            gap_days = (d2 - d1).days
            # Find nearest events globally
            events_on_d1 = [e for e in sorted_events_for_evidence 
                            if _is_care_event(e)
                            and _patient_scope_id(e) == patient_scope_id
                            and e.date and e.date.sort_date() == d1]
            events_on_d2 = [e for e in sorted_events_for_evidence 
                            if _is_care_event(e)
                            and _patient_scope_id(e) == patient_scope_id
                            and e.date and e.date.sort_date() == d2]
            boundary_acute = bool((events_on_d1 and _is_acute_event(events_on_d1[-1])) or (events_on_d2 and _is_acute_event(events_on_d2[0])))
            min_days = 45
            if gap_days < min_days:
                continue
            severity = "high" if gap_days >= 90 else "medium"
            
            # Stable hash for gap_id
            gap_seed = f"{patient_scope_id}{d1.isoformat()}{d2.isoformat()}global_gap_v1"
            gap_id = hashlib.sha256(gap_seed.encode()).hexdigest()[:16]
            
            last_event = events_on_d1[-1] if events_on_d1 else None
            next_event = events_on_d2[0] if events_on_d2 else None

            citation_ids = set()
            if last_event:
                citation_ids.update(last_event.citation_ids)
            if next_event:
                citation_ids.update(next_event.citation_ids)

            gaps.append({
                "gap_id": gap_id,
                "provider_id": None,
                "provider_display_name": None,
                "patient_scope_id": patient_scope_id,
                "start_date": d1.isoformat(),
                "end_date": d2.isoformat(),
                "gap_days": gap_days,
                "severity": severity,
                "rule_name": "global_gap",
                "rationale": "Post-acute continuity break" if boundary_acute else "No documented medical activity during this period",
                "evidence": {
                    "last_event_id": last_event.event_id if last_event else None,
                    "next_event_id": next_event.event_id if next_event else None,
                    "citation_ids": sorted(list(citation_ids))
                },
                "suggested_records_to_request": {
                    "provider_id": None,
                    "patient_scope_id": patient_scope_id,
                    "from": (d1 + timedelta(days=1)).isoformat(),
                    "to": (d2 - timedelta(days=1)).isoformat(),
                    "type": "Any medical provider records"
                }
            })

    # Sort gaps deterministically
    # 1. severity descending (high > medium)
    # 2. gap_days descending
    # 3. provider_display_name ascending (null last)
    # 4. start_date ascending
    def gap_sort_key(g):
        sev_score = 0 if g["severity"] == "high" else 1
        name = g["provider_display_name"] or "zzzzzzzz" # null last
        scope = g.get("patient_scope_id") or "zzzzzzzz"
        return (sev_score, -g["gap_days"], scope, name, g["start_date"])

    gaps.sort(key=gap_sort_key)

    # STEP 4 — Store results in EvidenceGraph.extensions
    substantive_events = [
        e for e in evidence_graph.events
        if _is_care_event(e) and getattr(e, "date", None) and e.date.sort_date().year > 1900
    ]
    care_window_days = (care_end - care_start).days if (care_start and care_end) else 0
    reeval_gap_logic = bool(care_window_days > 60 and len(substantive_events) < 10)

    summary = {
        "total_gaps": len(gaps),
        "provider_gap_count": sum(1 for g in gaps if g["rule_name"] == "provider_gap"),
        "global_gap_count": sum(1 for g in gaps if g["rule_name"] == "global_gap"),
        "high_severity_count": sum(1 for g in gaps if g["severity"] == "high"),
        "medium_severity_count": sum(1 for g in gaps if g["severity"] == "medium"),
        "patient_scope_count": len(sorted_global_dates_by_scope),
        "unassigned_events_excluded": sum(1 for e in evidence_graph.events if _patient_scope_id(e) == "ps_unknown"),
        "no_gap_detected": len(gaps) == 0,
        "no_gap_evidence": {
            "care_window_start": care_start.isoformat() if care_start else None,
            "care_window_end": care_end.isoformat() if care_end else None,
            "dated_substantive_event_count": len(substantive_events),
        } if len(gaps) == 0 else None,
        "care_window_days": care_window_days,
        "substantive_event_count": len(substantive_events),
        "reevaluate_gap_logic": reeval_gap_logic,
    }

    payload = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ruleset": {
            "provider_gap_medium_days": 30,
            "provider_gap_high_days": 60,
            "global_gap_medium_days": 45,
            "global_gap_high_days": 90,
            "care_window_start": care_start.isoformat() if care_start else None,
            "care_window_end": care_end.isoformat() if care_end else None,
        },
        "gaps": gaps,
        "summary": summary
    }
    payload["priority_requests_top3"] = _prioritize_missing_record_requests(gaps, limit=3)
    return MissingRecordsExtension.model_validate(payload).model_dump(mode="json")


def _prioritize_missing_record_requests(gaps: list[dict], *, limit: int = 3) -> list[dict]:
    ranked: list[dict] = []
    for gap in gaps:
        days = int(gap.get("gap_days") or 0)
        sev = str(gap.get("severity") or "medium").lower()
        sev_weight = 40 if sev == "high" else 20
        provider_named = bool((gap.get("provider_display_name") or "").strip())
        provider_bonus = 8 if provider_named else 0
        acute_bonus = 10 if "post-acute" in str(gap.get("rationale") or "").lower() else 0
        score = min(100, sev_weight + min(50, int(days / 2)) + provider_bonus + acute_bonus)
        req = dict(gap.get("suggested_records_to_request") or {})
        ranked.append(
            {
                "gap_id": str(gap.get("gap_id") or ""),
                "priority_score": score,
                "priority_tier": "High" if score >= 75 else ("Medium" if score >= 45 else "Low"),
                "provider_display_name": str(gap.get("provider_display_name") or "Any provider"),
                "date_range": {
                    "from": str(req.get("from") or ""),
                    "to": str(req.get("to") or ""),
                },
                "request_type": str(req.get("type") or "Medical records"),
                "rationale": str(gap.get("rationale") or "Potential continuity gap requiring source records."),
                "citation_ids": list(((gap.get("evidence") or {}).get("citation_ids") or []))[:3],
            }
        )
    ranked.sort(key=lambda r: (-int(r.get("priority_score") or 0), str(r.get("gap_id") or "")))
    out: list[dict] = []
    for idx, item in enumerate(ranked[:limit], start=1):
        row = dict(item)
        row["rank"] = idx
        out.append(row)
    return out


def render_missing_records(
    run_id: str,
    payload: dict,
) -> tuple[Optional[ArtifactRef], Optional[ArtifactRef]]:
    """Save missing_records artifacts and return refs."""
    import csv
    import io

    gaps = payload.get("gaps", [])

    # CSV Generation
    csv_buf = io.StringIO()
    csv_cols = [
        "gap_id", "severity", "rule_name", "provider_id", "provider_display_name", 
        "start_date", "end_date", "gap_days", "rationale"
    ]
    writer = csv.DictWriter(csv_buf, fieldnames=csv_cols, extrasaction="ignore")
    writer.writeheader()
    for gap in gaps:
        writer.writerow(gap)
    
    csv_bytes = csv_buf.getvalue().encode("utf-8")
    csv_path = save_artifact(run_id, "missing_records.csv", csv_bytes)
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    csv_ref = ArtifactRef(uri=str(csv_path), sha256=csv_sha, bytes=len(csv_bytes))

    # JSON Generation
    json_bytes = json.dumps(payload, indent=2, default=str).encode("utf-8")
    json_path = save_artifact(run_id, "missing_records.json", json_bytes)
    json_sha = hashlib.sha256(json_bytes).hexdigest()
    json_ref = ArtifactRef(uri=str(json_path), sha256=json_sha, bytes=len(json_bytes))

    return csv_ref, json_ref
