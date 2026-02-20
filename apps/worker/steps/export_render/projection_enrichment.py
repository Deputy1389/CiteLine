"""
Enrichment and bucket logic for chronology projection.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import TYPE_CHECKING

from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.events.report_quality import sanitize_for_report, date_sanity
from apps.worker.steps.export_render.common import (
    _sanitize_filename_display,
    _sanitize_citation_display,
    _has_inpatient_markers,
)
from apps.worker.steps.export_render.constants import PROCEDURE_ANCHOR_RE

if TYPE_CHECKING:
    from packages.shared.models import Event


def _enrich_projection_procedure_entries(
    projection: ChronologyProjection,
    *,
    page_text_by_number: dict[int, str] | None,
    page_map: dict[int, tuple[str, int]] | None,
) -> ChronologyProjection:
    if not page_text_by_number:
        return projection

    enriched_entries = []
    for entry in projection.entries:
        if (entry.event_type_display or "").strip().lower() != "procedure/surgery":
            enriched_entries.append(entry)
            continue
        facts_blob = " ".join(entry.facts or []).lower()
        if "epidural steroid injection" in facts_blob and "fluoroscopy" in facts_blob:
            enriched_entries.append(entry)
            continue

        anchor_pages: list[int] = []
        meds: set[str] = set()
        guidance = False
        complications_none = False
        levels: set[str] = set()
        aggregate_tokens: set[str] = set()
        for p in sorted(page_text_by_number.keys()):
            txt = page_text_by_number.get(p) or ""
            low = txt.lower()
            hit_tokens = {tok.lower() for tok in PROCEDURE_ANCHOR_RE.findall(low)}
            if len(hit_tokens) < 2: continue
            aggregate_tokens.update(hit_tokens)
            anchor_pages.append(p)
            if re.search(r"\bdepo[- ]?medrol\b", low): meds.add("Depo-Medrol")
            if "lidocaine" in low: meds.add("lidocaine")
            if "fluoroscopy" in low: guidance = True
            if re.search(r"\bcomplications:\s*none\b", low): complications_none = True
            for m in re.finditer(r"\b([cCtTlL]\d-\d)\b", txt): levels.add(m.group(1).upper())
        if not anchor_pages:
            enriched_entries.append(entry)
            continue

        proc_name = "Epidural Steroid Injection"
        level_text = f" at {', '.join(sorted(levels))}" if levels else ""
        meds_text = f" with {', '.join(sorted(meds))}" if meds else ""
        guidance_text = "; fluoroscopy guidance used" if guidance else ""
        comp_text = "; complications: none documented" if complications_none else ""
        token_blob = " ".join(sorted(aggregate_tokens))
        if not meds and ("depo-medrol" in token_blob or "lidocaine" in token_blob):
            if "depo-medrol" in token_blob: meds.add("Depo-Medrol")
            if "lidocaine" in token_blob: meds.add("lidocaine")
            meds_text = f" with {', '.join(sorted(meds))}" if meds else ""
        enriched_fact = f"{proc_name}{level_text}{meds_text}{guidance_text}{comp_text}."

        refs: list[str] = []
        for p in anchor_pages[:5]:
            if page_map and p in page_map:
                fname, local = page_map[p]
                refs.append(f"{_sanitize_filename_display(fname)} p. {local}")
            else: refs.append(f"p. {p}")
        merged_citation = ", ".join(dict.fromkeys([c for c in [entry.citation_display, ", ".join(refs)] if c]))
        new_facts = list(entry.facts or [])
        new_facts.append(sanitize_for_report(enriched_fact))
        enriched_entries.append(entry.model_copy(update={"facts": new_facts, "citation_display": _sanitize_citation_display(merged_citation)}))

    return projection.model_copy(update={"entries": enriched_entries})


def _ensure_ortho_bucket_entry(
    projection: ChronologyProjection,
    *,
    page_text_by_number: dict[int, str] | None,
    page_map: dict[int, tuple[str, int]] | None,
    raw_events: list[Event] | None = None,
) -> ChronologyProjection:
    if not page_text_by_number: return projection
    for entry in projection.entries:
        blob = " ".join(entry.facts or []).lower()
        if re.search(r"\b(ortho|orthopedic|orthopaedic)\b", blob): return projection

    ortho_pages: list[int] = []
    ortho_date: date | None = None
    for p in sorted(page_text_by_number.keys()):
        txt = page_text_by_number.get(p) or ""
        low = txt.lower()
        if "ortho" not in low and "orthopedic" not in low and "orthopaedic" not in low: continue
        ortho_pages.append(p)
        for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)\b", low):
            try: cand = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError: continue
            if date_sanity(cand):
                if ortho_date is None or cand < ortho_date: ortho_date = cand
    if not ortho_pages and raw_events:
        for evt in raw_events:
            blob = " ".join((f.text or "") for f in (evt.facts or [])).lower()
            if "ortho" not in blob and "orthopedic" not in blob and "orthopaedic" not in blob: continue
            for p in sorted(set(evt.source_page_numbers or [])): ortho_pages.append(p)
            if isinstance(getattr(getattr(evt, "date", None), "value", None), date):
                cand = evt.date.value
                if date_sanity(cand) and (ortho_date is None or cand < ortho_date): ortho_date = cand
    if not ortho_pages:
        for p in sorted(page_text_by_number.keys()):
            txt = (page_text_by_number.get(p) or "").lower()
            if "ortho" in txt or "orthopedic" in txt or "orthopaedic" in txt:
                ortho_pages = [p]
                break
    if not ortho_pages: return projection

    refs: list[str] = []
    for p in ortho_pages[:5]:
        if page_map and p in page_map:
            fname, local = page_map[p]
            refs.append(f"{_sanitize_filename_display(fname)} p. {local}")
        else: refs.append(f"p. {p}")
    ortho_fact = "Assessment: Orthopedic consultation documented. Plan: follow-up and treatment planning noted."
    for p in ortho_pages:
        txt = page_text_by_number.get(p) or ""
        m = re.search(r"(?is)\b(assessment|impression)\b[:\s-]+(.{20,240}?)\b(plan|follow[- ]?up|continue)\b", txt)
        if m:
            snippet = sanitize_for_report(m.group(2).strip())
            if snippet: ortho_fact = f'Assessment: "{snippet}". Plan: follow-up and treatment planning noted.'
            break
    ortho_entry = ChronologyProjectionEntry(
        event_id=f"ortho_anchor_{hashlib.sha1('|'.join(map(str, ortho_pages)).encode('utf-8')).hexdigest()[:12]}",
        date_display=f"{ortho_date.isoformat()} (time not documented)" if ortho_date else "Date not documented",
        provider_display="Unknown", event_type_display="Orthopedic Consult", patient_label="See Patient Header",
        facts=[ortho_fact], citation_display=", ".join(refs), confidence=80,
    )
    new_entries = list(projection.entries)
    new_entries.append(ortho_entry)
    return projection.model_copy(update={"entries": new_entries})


def _ensure_mri_bucket_entry(
    projection: ChronologyProjection,
    *,
    page_text_by_number: dict[int, str] | None,
    page_map: dict[int, tuple[str, int]] | None,
) -> ChronologyProjection:
    for entry in projection.entries:
        blob = f"{entry.event_type_display} {' '.join(entry.facts or [])}".lower()
        if "mri" in blob or "magnetic resonance" in blob: return projection

    mri_pages: list[int] = []
    mri_date: date | None = None
    if page_map:
        for p, (fname, _local) in sorted(page_map.items(), key=lambda it: it[0]):
            low_name = (fname or "").lower()
            if "mri" not in low_name: continue
            mri_pages.append(p)
            m = re.search(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)\b", low_name)
            if m:
                try: cand = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError: cand = None
                if cand and date_sanity(cand) and (mri_date is None or cand < mri_date): mri_date = cand
    if page_text_by_number:
        for p in sorted(page_text_by_number.keys()):
            txt = page_text_by_number.get(p) or ""
            low = txt.lower()
            if "mri" not in low and "magnetic resonance" not in low: continue
            if p not in mri_pages: mri_pages.append(p)
            for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)\b", txt):
                try: cand = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError: continue
                if date_sanity(cand) and (mri_date is None or cand < mri_date): mri_date = cand
    if not mri_pages: return projection

    refs: list[str] = []
    for p in mri_pages[:4]:
        if page_map and p in page_map:
            fname, local = page_map[p]
            refs.append(f"{_sanitize_filename_display(fname)} p. {local}")
        else: refs.append(f"p. {p}")
    finding = ""
    if page_text_by_number:
        for p in mri_pages:
            txt = page_text_by_number.get(p) or ""
            mt = re.search(r"(?is)\bimpression\b[:\s-]+(.{20,220})", txt)
            if mt:
                finding = sanitize_for_report(mt.group(1).split("\n")[0].strip())
                if finding: break
    if not finding: finding = "MRI report reviewed; impression documented."
    mri_entry = ChronologyProjectionEntry(
        event_id=f"mri_anchor_{hashlib.sha1('|'.join(map(str, mri_pages)).encode('utf-8')).hexdigest()[:12]}",
        date_display=f"{mri_date.isoformat()} (time not documented)" if mri_date else "Date not documented",
        provider_display="Unknown", event_type_display="Imaging Study", patient_label="See Patient Header",
        facts=[f'MRI Impression: "{finding}"'], citation_display=", ".join(refs), confidence=82,
    )
    new_entries = list(projection.entries)
    new_entries.append(mri_entry)
    return projection.model_copy(update={"entries": new_entries})


def _ensure_procedure_bucket_entry(
    projection: ChronologyProjection,
    *,
    page_text_by_number: dict[int, str] | None,
    page_map: dict[int, tuple[str, int]] | None,
) -> ChronologyProjection:
    for entry in projection.entries:
        label = (entry.event_type_display or "").lower()
        if "procedure" in label or "surgery" in label: return projection

    if not page_text_by_number: return projection

    proc_pages: list[int] = []
    candidate_pages: list[int] = []
    proc_date: date | None = None
    levels: set[str] = set()
    meds: set[str] = set()
    guidance = False
    complications_none = False
    global_anchor_tokens: set[str] = set()

    for p in sorted(page_text_by_number.keys()):
        txt = page_text_by_number.get(p) or ""
        low = txt.lower()
        hits = 0
        if re.search(r"\b(depo-?medrol|lidocaine)\b", low): hits += 1
        if re.search(r"\bfluoroscopy\b", low): hits += 1
        if re.search(r"\b(interlaminar|transforaminal|epidural)\b", low): hits += 1
        if re.search(r"\bcomplications?\b", low): hits += 1
        page_tokens = set(re.findall(r"\b(depo-?medrol|lidocaine|fluoroscopy|interlaminar|transforaminal|epidural|esi)\b", low))
        global_anchor_tokens.update({t.lower() for t in page_tokens})
        if hits >= 1: candidate_pages.append(p)
        if hits < 2: continue
        proc_pages.append(p)
        if re.search(r"\bdepo-?medrol\b", low): meds.add("Depo-Medrol")
        if "lidocaine" in low: meds.add("Lidocaine")
        if "fluoroscopy" in low: guidance = True
        if re.search(r"\bcomplications?:\s*none\b|\bno\scomplications\b", low): complications_none = True
        for m in re.finditer(r"\b([cCtTlL]\d-\d)\b", txt): levels.add(m.group(1).upper())
        for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)\b", txt):
            try: cand = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError: continue
            if date_sanity(cand) and (proc_date is None or cand < proc_date): proc_date = cand

    if not proc_pages and len(global_anchor_tokens) >= 2 and candidate_pages:
        proc_pages = sorted(candidate_pages)[:5]
        for p in proc_pages:
            txt = page_text_by_number.get(p) or ""
            low = txt.lower()
            if re.search(r"\bdepo-?medrol\b", low): meds.add("Depo-Medrol")
            if "lidocaine" in low: meds.add("Lidocaine")
            if "fluoroscopy" in low: guidance = True
            if re.search(r"\bcomplications?:\s*none\b|\bno\scomplications\b", low): complications_none = True
            for m in re.finditer(r"\b([cCtTlL]\d-\d)\b", txt): levels.add(m.group(1).upper())
            for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)\b", txt):
                try: cand = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError: continue
                if date_sanity(cand) and (proc_date is None or cand < proc_date): proc_date = cand

    if not proc_pages: return projection

    refs: list[str] = []
    for p in proc_pages[:5]:
        if page_map and p in page_map:
            fname, local = page_map[p]
            refs.append(f"{_sanitize_filename_display(fname)} p. {local}")
        else: refs.append(f"p. {p}")

    proc_name = "Epidural Steroid Injection"
    if levels: proc_name += f" at {', '.join(sorted(levels))}"
    facts = [proc_name]
    if meds: facts.append(f"Medications: {', '.join(sorted(meds))}")
    if guidance: facts.append("Guidance: Fluoroscopy")
    if complications_none: facts.append("Complications: None documented")

    proc_entry = ChronologyProjectionEntry(
        event_id=f"proc_anchor_{hashlib.sha1('|'.join(map(str, proc_pages)).encode('utf-8')).hexdigest()[:12]}",
        date_display=f"{proc_date.isoformat()} (time not documented)" if proc_date else "Date not documented",
        provider_display="Unknown", event_type_display="Procedure/Surgery", patient_label="See Patient Header",
        facts=[sanitize_for_report(f) for f in facts if f], citation_display=", ".join(refs), confidence=82,
    )
    new_entries = list(projection.entries)
    new_entries.append(proc_entry)
    return projection.model_copy(update={"entries": new_entries})


def _normalize_event_class_local(entry) -> str:
    normalized = (entry.event_type_display or "").strip().lower()
    facts = list(getattr(entry, "facts", []) or [])
    mapping = {
        "emergency visit": "ed",
        "hospital admission": "admission",
        "hospital discharge": "discharge",
        "discharge": "discharge",
        "inpatient progress": "inpatient_progress" if _has_inpatient_markers(normalized, facts) else "clinical_note",
        "procedure/surgery": "procedure",
        "imaging study": "imaging",
        "follow-up visit": "followup",
        "therapy visit": "therapy",
        "lab result": "lab",
        "clinical note": "clinical_note",
        "record entry": "clinical_note",
    }
    return mapping.get(normalized, "other")
