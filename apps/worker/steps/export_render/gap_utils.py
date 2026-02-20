"""
Gap-specific extraction and collapsing logic for export rendering.
"""
from __future__ import annotations

import uuid
import re
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

from apps.worker.steps.events.report_quality import date_sanity
from apps.worker.steps.export_render.common import (
    _pages_ref,
    parse_date_string,
)

if TYPE_CHECKING:
    from packages.shared.models import Event, Gap


def _material_gap_rows(gap_list: list[Gap], entries_by_patient: dict[str, list], raw_event_by_id: dict[str, Event], page_map=None) -> list[dict]:
    from apps.worker.steps.export_render.common import _extract_disposition
    rows: list[dict] = []
    entry_by_id = {e.event_id: e for ents in entries_by_patient.values() for e in ents}
    hospice_dates_by_patient: dict[str, list[date]] = defaultdict(list)
    for plabel, ents in entries_by_patient.items():
        for ent in ents:
            dt = parse_date_string(ent.date_display)
            if dt and (_extract_disposition(" ".join(ent.facts)) == "Hospice" or re.search(r"\bhospice\b", " ".join(ent.facts).lower())):
                hospice_dates_by_patient[plabel].append(dt)
    for plabel in hospice_dates_by_patient: hospice_dates_by_patient[plabel].sort()

    def _entry_from_raw(evt: Event) -> dict:
        dt = evt.date.sort_date() if evt.date else None
        return {
            "date_display": f"{dt.isoformat()} (time not documented)" if dt else "Date not documented",
            "event_type_display": evt.event_type.value.replace("_", " ").title(),
            "citation_display": _pages_ref(evt, page_map),
            "event_id": evt.event_id,
            "facts_blob": " ".join((f.text or "") for f in evt.facts).lower(),
        }

    for gap in gap_list:
        if gap.start_date and not date_sanity(gap.start_date): continue
        if gap.end_date and not date_sanity(gap.end_date): continue
        related_ids = list(getattr(gap, "related_event_ids", []) or [])
        labels = sorted({entry_by_id[eid].patient_label for eid in related_ids if eid in entry_by_id and entry_by_id[eid].patient_label != "Unknown Patient"})
        if len(labels) != 1:
            candidate_labels = set()
            for plabel, pentries in entries_by_patient.items():
                if plabel == "Unknown Patient": continue
                dated = sorted((parse_date_string(ent.date_display), ent.event_id) for ent in pentries if parse_date_string(ent.date_display))
                if dated and gap.start_date >= dated[0][0] and gap.end_date <= dated[-1][0]: candidate_labels.add(plabel)
            if len(candidate_labels) == 1: labels = sorted(candidate_labels)
            elif len(entries_by_patient) == 1: labels = [next(iter(entries_by_patient.keys()))]
            else: continue
        
        patient_label = labels[0]
        last_before = first_after = None
        if len(related_ids) >= 2 and related_ids[0] in raw_event_by_id and related_ids[1] in raw_event_by_id:
            last_before = _entry_from_raw(raw_event_by_id[related_ids[0]])
            first_after = _entry_from_raw(raw_event_by_id[related_ids[1]])
        else:
            p_entries = entries_by_patient.get(patient_label, [])
            dated_ents = sorted([(ent, parse_date_string(ent.date_display)) for ent in p_entries if parse_date_string(ent.date_display)], key=lambda x: (x[1], x[0].event_id))
            for idx in range(len(dated_ents) - 1):
                if dated_ents[idx][1] <= gap.start_date and dated_ents[idx+1][1] >= gap.end_date:
                    last_before = {"date_display": dated_ents[idx][0].date_display, "event_type_display": dated_ents[idx][0].event_type_display, "citation_display": dated_ents[idx][0].citation_display, "event_id": dated_ents[idx][0].event_id, "facts_blob": " ".join(dated_ents[idx][0].facts).lower()}
                    first_after = {"date_display": dated_ents[idx+1][0].date_display, "event_type_display": dated_ents[idx+1][0].event_type_display, "citation_display": dated_ents[idx+1][0].citation_display, "event_id": dated_ents[idx+1][0].event_id, "facts_blob": " ".join(dated_ents[idx+1][0].facts).lower()}
                    break
        if not last_before or not first_after: continue

        et = (last_before.get("event_type_display", "") or "").lower()
        facts = last_before.get("facts_blob", "")
        rationale_tag = None
        if "hospice" in facts and any(hd <= gap.start_date for hd in hospice_dates_by_patient.get(patient_label, [])): rationale_tag = "hospice_continuity_break"
        elif "skilled nursing" in facts or "snf" in facts or "rehab" in facts: rationale_tag = "rehab_snf_transition_gap"
        elif any(k in et for k in ("hospital admission", "hospital discharge", "emergency visit")): rationale_tag = "post_admission_followup_missing"
        elif "procedure" in et or "surgery" in et: rationale_tag = "post_procedure_followup_missing"
        
        duration = int(gap.duration_days or 0)
        if (rationale_tag in {"post_admission_followup_missing", "post_procedure_followup_missing", "hospice_continuity_break", "rehab_snf_transition_gap"} and duration >= 60) or duration >= 1:
            rows.append({"gap": gap, "patient_label": patient_label, "last_before": last_before, "first_after": first_after, "rationale_tag": rationale_tag or "routine_continuity_gap"})
    
    final_rows = []
    by_p = defaultdict(list)
    for r in rows: by_p[r["patient_label"]].append(r)
    for p in sorted(by_p):
        prow = sorted(by_p[p], key=lambda r: (r["gap"].start_date, r["gap"].end_date, r["gap"].gap_id))
        i = 0
        while i < len(prow):
            if prow[i].get("rationale_tag") != "routine_continuity_gap":
                final_rows.append(prow[i])
                i += 1
                continue
            run = [prow[i]]
            j = i + 1
            while j < len(prow) and prow[j].get("rationale_tag") == "routine_continuity_gap" and abs(int(run[-1]["gap"].duration_days or 0) - int(prow[j]["gap"].duration_days or 0)) <= 3:
                run.append(prow[j])
                j += 1
            if len(run) >= 3:
                from packages.shared.models import Gap
                final_rows.append({"gap": Gap(gap_id=f"collapsed_{uuid.uuid4().hex[:12]}", start_date=run[0]["gap"].start_date, end_date=run[-1]["gap"].end_date, duration_days=(run[-1]["gap"].end_date - run[0]["gap"].start_date).days, threshold_days=540, confidence=min(int(run[0]["gap"].confidence or 80), int(run[-1]["gap"].confidence or 80)), related_event_ids=[str(run[0]["last_before"].get("event_id", "")), str(run[-1]["first_after"].get("event_id", ""))]), "patient_label": p, "last_before": run[0]["last_before"], "first_after": run[-1]["first_after"], "rationale_tag": "routine_continuity_gap_collapsed", "collapse_label": "Repeated annual continuity gaps collapsed"})
                i = j
            else:
                for rr in run:
                    if int(rr["gap"].duration_days or 0) >= 540: final_rows.append(rr)
                i = j
    return final_rows
