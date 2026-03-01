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
    from packages.shared.models import Event, Gap, Citation


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


def build_gap_anchor_metadata_rows(
    missing_records_payload: dict | None,
    all_citations: list["Citation"] | None,
    page_map=None,
) -> list[dict]:
    payload = missing_records_payload if isinstance(missing_records_payload, dict) else {}
    gaps = [g for g in (payload.get("gaps") or []) if isinstance(g, dict)]
    if not gaps:
        return []
    cit_by_id: dict[str, "Citation"] = {}
    for c in (all_citations or []):
        cid = str(getattr(c, "citation_id", "") or "").strip()
        if cid:
            cit_by_id[cid] = c

    rows: list[dict] = []
    for g in gaps:
        evidence = g.get("evidence") if isinstance(g.get("evidence"), dict) else {}
        cids = [str(c) for c in (evidence.get("citation_ids") or []) if str(c)]
        refs: list[dict] = []
        seen_pages: set[str] = set()
        for cid in cids:
            c = cit_by_id.get(cid)
            if not c:
                continue
            try:
                global_page = int(getattr(c, "page_number", 0) or 0)
            except Exception:
                global_page = 0
            local_page = global_page
            if page_map and global_page in page_map:
                _mapped_name, mapped_local = page_map[global_page]
                try:
                    local_page = int(mapped_local)
                except Exception:
                    local_page = global_page
            page_key = str(local_page or global_page)
            if page_key in seen_pages:
                continue
            seen_pages.add(page_key)
            refs.append(
                {
                    "citation_id": cid,
                    "global_page": global_page,
                    "local_page": local_page,
                    "snippet": str(getattr(c, "snippet", "") or "").strip(),
                }
            )
        rows.append(
            {
                "gap_id": str(g.get("gap_id") or ""),
                "gap_days": int(g.get("gap_days") or g.get("duration_days") or 0),
                "threshold_days": int((payload.get("ruleset") or {}).get("global_gap_medium_days") or g.get("threshold_days") or 45),
                "severity": str(g.get("severity") or ""),
                "rule_name": str(g.get("rule_name") or ""),
                "start_date": str(g.get("start_date") or ""),
                "end_date": str(g.get("end_date") or ""),
                "gap_start_event_id": str(evidence.get("last_event_id") or ""),
                "gap_end_event_id": str(evidence.get("next_event_id") or ""),
                "citation_ids": cids,
                "citation_refs": refs,
                "gap_start_page": (refs[0]["local_page"] if len(refs) >= 1 else None),
                "gap_end_page": (refs[1]["local_page"] if len(refs) >= 2 else None),
                "anchors_complete": len(refs) >= 2,
            }
        )
    return rows
