from __future__ import annotations
from datetime import date, datetime, timezone, timedelta
from dataclasses import dataclass, asdict
import re
import hashlib
import textwrap
from collections import defaultdict
from typing import Any

from apps.worker.project.models import ChronologyProjection, ChronologyProjectionEntry
from apps.worker.steps.events.report_quality import (
    date_sanity,
    injury_canonicalization,
    is_reportable_fact,
    procedure_canonicalization,
    sanitize_for_report,
    surgery_classifier_guard,
)
from apps.worker.lib.noise_filter import is_noise_span
from packages.shared.models import Event, Provider

# New Utility Imports
from packages.shared.utils.render_utils import (
    projection_date_display as _projection_date_display,
    iso_date_display as _iso_date_display,
    get_provider_name as _provider_name,
    get_citation_display as _citation_display,
    infer_page_patient_labels,
    get_event_patient_label as _event_patient_label,
)
from packages.shared.utils.noise_utils import (
    is_vitals_heavy as _is_vitals_heavy,
    is_header_noise_fact as _is_header_noise_fact,
    is_flowsheet_noise as _is_flowsheet_noise,
)
from packages.shared.utils.extraction_utils import (
    extract_pt_elements as _extract_pt_elements,
    extract_imaging_elements as _extract_imaging_elements,
)
from packages.shared.utils.scoring_utils import (
    is_high_value_event as _is_high_value_event,
    classify_projection_entry as _classify_projection_entry,
    bucket_for_required_coverage as _bucket_for_required_coverage,
    projection_entry_score as _projection_entry_score,
    entry_substance_score as _entry_substance_score,
    is_substantive_entry as _is_substantive_entry,
)
from packages.shared.utils.date_utils import (
    parse_fact_dates as _parse_fact_dates,
    fact_temporally_consistent as _fact_temporally_consistent,
    strip_conflicting_timestamps as _strip_conflicting_timestamps,
)

INPATIENT_MARKER_RE = re.compile(
    r"\b(admission order|hospital day|inpatient service|discharge summary|admitted|inpatient|hospitalist|icu|intensive care)\b",
    re.IGNORECASE,
)
MIN_SUBSTANCE_THRESHOLD = 1
HIGH_SUBSTANCE_THRESHOLD = 2
UTILITY_EPSILON = 0.03
UTILITY_CONSECUTIVE_LOW_K = 8
SELECTION_HARD_MAX_ROWS = 250

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

def _is_substantive_event(event: Event) -> bool:
    joined_facts = " ".join(f.text for f in event.facts).lower()
    keywords = (
        "diagnosis", "assessment", "impression", "problem", "radiculopathy",
        "fracture", "tear", "infection", "stenosis", "sprain", "strain",
        "medication", "prescribed", "started", "stopped", "procedure",
        "surgery", "injection", "mri", "x-ray", "ct scan", "ultrasound",
        "physician overread", "medical director", "care summary"
    )
    if any(k in joined_facts for k in keywords):
        return True
    if len(event.facts) > 3:
        return True
    return False

def _is_high_substance_entry(entry: ChronologyProjectionEntry) -> bool:
    if not _is_substantive_entry(entry):
        return False
    return _entry_substance_score(entry) >= HIGH_SUBSTANCE_THRESHOLD

def _entry_date_only(entry: ChronologyProjectionEntry) -> date | None:
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", entry.date_display or "")
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None

def _entry_novelty_tokens(entry: ChronologyProjectionEntry) -> set[str]:
    blob = " ".join(entry.facts or []).lower()
    tokens = set(re.findall(r"[a-z][a-z0-9_-]{2,}", blob))
    tokens.update((entry.event_type_display or "").lower().split())
    provider = (entry.provider_display or "").strip().lower()
    if provider and provider != "unknown":
        tokens.add(f"prov:{provider}")
    bucket = _bucket_for_required_coverage(entry)
    if bucket:
        tokens.add(f"bucket:{bucket}")
    return tokens

def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    if union <= 0:
        return 0.0
    return inter / union

def _event_has_renderable_snippet(entry: ChronologyProjectionEntry) -> bool:
    if not (entry.citation_display or "").strip():
        return False
    for fact in entry.facts or []:
        cleaned = sanitize_for_report(fact or "").strip()
        if len(cleaned) < 12:
            continue
        if re.search(r"\b(limited detail|encounter recorded|continuity of care|documentation noted|identified from source|markers|not stated in records)\b", cleaned.lower()):
            continue
        if _classify_projection_entry(entry) == "therapy":
            low = cleaned.lower()
            metric_hits = 0
            if re.search(r"\bpain(?:\s*(?:score|severity|level))?\s*[:=]?\s*\d{1,2}\s*/\s*10\b", low):
                metric_hits += 1
            if re.search(r"\b(rom|range of motion)\b.*\b\d+\s*deg\b|\b\d+\s*deg\b", low):
                metric_hits += 1
            if re.search(r"\bstrength\b.*\b[0-5](?:\.\d+)?\s*/\s*5\b|\b[0-5](?:\.\d+)?\s*/\s*5\b", low):
                metric_hits += 1
            if re.search(r"\b(work restriction|return to work|functional limitation|adl)\b", low):
                metric_hits += 1
            if metric_hits < 2:
                continue
        return True
    return False

def _temporal_coverage_gain(entry: ChronologyProjectionEntry, selected_dates: list[date]) -> float:
    d = _entry_date_only(entry)
    if d is None:
        return 0.05
    if not selected_dates:
        return 1.0
    nearest = min(abs((d - sd).days) for sd in selected_dates)
    if nearest >= 30: return 1.0
    if nearest >= 14: return 0.65
    if nearest >= 7: return 0.4
    if nearest >= 2: return 0.2
    return 0.05

def _novelty_gain(entry: ChronologyProjectionEntry, selected: list[ChronologyProjectionEntry], token_cache: dict[str, set[str]]) -> float:
    current = token_cache.get(entry.event_id) or _entry_novelty_tokens(entry)
    if not selected:
        return 1.0
    best_sim = 0.0
    for s in selected:
        st = token_cache.get(s.event_id)
        if st is None:
            st = _entry_novelty_tokens(s)
            token_cache[s.event_id] = st
        best_sim = max(best_sim, _jaccard_similarity(current, st))
    return max(0.0, 1.0 - best_sim)

def _redundancy_penalty(entry: ChronologyProjectionEntry, selected: list[ChronologyProjectionEntry], token_cache: dict[str, set[str]]) -> float:
    if not selected:
        return 0.0
    d = _entry_date_only(entry)
    bucket = _bucket_for_required_coverage(entry)
    current = token_cache.get(entry.event_id) or _entry_novelty_tokens(entry)
    max_pen = 0.0
    for s in selected:
        entry_base = entry.event_id.split("::", 1)[0]
        selected_base = s.event_id.split("::", 1)[0]
        same_day = d is not None and d == _entry_date_only(s)
        same_bucket = bucket is not None and bucket == _bucket_for_required_coverage(s)
        st = token_cache.get(s.event_id)
        if st is None:
            st = _entry_novelty_tokens(s)
            token_cache[s.event_id] = st
        sim = _jaccard_similarity(current, st)
        pen = 0.0
        if entry_base == selected_base: pen += 0.75
        if same_day: pen += 0.3
        if same_bucket: pen += 0.25
        pen += sim * 0.45
        max_pen = max(max_pen, min(1.0, pen))
    return max_pen

def _collapse_repetitive_entries(rows: list[ChronologyProjectionEntry]) -> list[ChronologyProjectionEntry]:
    if len(rows) <= 100: return rows
    grouped: dict[tuple[str, str, str, str, str], list[ChronologyProjectionEntry]] = defaultdict(list)
    for row in rows:
        facts_blob = " ".join(row.facts).lower()
        et = (row.event_type_display or "").lower()
        marker = "generic"
        if "therapy" in et or "pt" in facts_blob: marker = "pt"
        elif "inpatient" in et or "nursing" in facts_blob or "flowsheet" in facts_blob: marker = "nursing"
        grouped[(row.patient_label, row.date_display, row.provider_display, marker, row.event_type_display)].append(row)
    out: list[ChronologyProjectionEntry] = []
    for key in sorted(grouped.keys()):
        items = grouped[key]
        if len(items) == 1:
            out.append(items[0])
            continue
        patient, date_display, provider, marker, event_type = key
        merged_facts: list[str] = []
        seen = set()
        for it in items:
            for fact in it.facts:
                norm = fact.strip().lower()
                if not norm or norm in seen: continue
                seen.add(norm)
                merged_facts.append(fact)
                if len(merged_facts) >= 4: break
            if len(merged_facts) >= 4: break
        if marker == "pt": merged_facts = [f"PT sessions on {date_display.split(' ')[0]} summarized: gradual progression documented with cited metrics."]
        elif marker == "nursing": merged_facts = [f"Nursing/flowsheet documentation on {date_display.split(' ')[0]} consolidated; see citations for details."]
        merged_citations = ", ".join(sorted({it.citation_display for it in items if it.citation_display}))
        out.append(ChronologyProjectionEntry(
            event_id=hashlib.sha1("|".join(sorted(it.event_id for it in items)).encode("utf-8")).hexdigest()[:16],
            date_display=date_display, provider_display=provider, event_type_display=event_type, patient_label=patient,
            facts=merged_facts or items[0].facts[:2], citation_display=merged_citations or items[0].citation_display,
            confidence=max(it.confidence for it in items)
        ))
    return out

def _split_composite_entries(rows: list[ChronologyProjectionEntry], total_pages: int) -> list[ChronologyProjectionEntry]:
    if total_pages <= 300: return rows
    out: list[ChronologyProjectionEntry] = []
    for row in rows:
        if (row.event_type_display or "").lower() in {"therapy visit", "imaging study"}:
            out.append(row); continue
        facts = list(row.facts or [])
        if not facts:
            out.append(row); continue
        snippets: list[str] = []
        for fact in facts:
            for seg in re.split(r"[.;]\s+", fact):
                seg = seg.strip()
                if not seg: continue
                if re.search(r"\b(impression|assessment|plan|diagnosis|procedure|injection|rom|range of motion|strength|pain|work restriction|return to work|chief complaint|hpi|history of present illness|radicular|disc protrusion|mri|x-?ray)\b", seg.lower()):
                    snippets.append(seg)
                elif len(seg) >= 28 and re.search(r"\d", seg):
                    snippets.append(seg)
        dedup_snippets: list[str] = []
        seen_snips: set[str] = set()
        for s in snippets:
            key = s.lower()
            if key in seen_snips: continue
            seen_snips.add(key); dedup_snippets.append(s)
        snippets = dedup_snippets
        if len(snippets) <= 3:
            out.append(row); continue
        snippets = snippets[:8]
        for idx, snippet in enumerate(snippets, start=1):
            out.append(ChronologyProjectionEntry(
                event_id=f"{row.event_id}::split{idx}", date_display=row.date_display, provider_display=row.provider_display,
                event_type_display=row.event_type_display, patient_label=row.patient_label, facts=[snippet],
                citation_display=row.citation_display, confidence=row.confidence
            ))
    return out

def _aggregate_pt_weekly_rows(rows: list[ChronologyProjectionEntry], total_pages: int) -> list[ChronologyProjectionEntry]:
    if total_pages <= 300: return rows
    grouped: dict[tuple[str, str, str, date], list[ChronologyProjectionEntry]] = defaultdict(list)
    passthrough: list[ChronologyProjectionEntry] = []
    for row in rows:
        if (row.event_type_display or "").lower() != "therapy visit":
            passthrough.append(row); continue
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", row.date_display or "")
        if not m:
            passthrough.append(row); continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            passthrough.append(row); continue
        week_start = d - timedelta(days=d.weekday())
        region = "general"
        facts_blob = " ".join(row.facts).lower()
        if "cervical" in facts_blob: region = "cervical"
        elif "lumbar" in facts_blob: region = "lumbar"
        grouped[(row.patient_label, row.provider_display, region, week_start)].append(row)
    aggregated: list[ChronologyProjectionEntry] = []
    for key in sorted(grouped.keys(), key=lambda k: (k[0], k[3], k[1], k[2])):
        patient, provider, region, week_start = key
        items = grouped[key]
        pain_vals, rom_vals, strength_vals, plan_snips, citations = [], [], [], [], set()
        for it in items:
            citations.update(part.strip() for part in (it.citation_display or "").split(",") if part.strip())
            for fact in it.facts:
                low = fact.lower()
                for m in re.finditer(r"\bpain(?:\s*(?:score|severity|level))?\s*[:=]?\s*(\d{1,2})\s*/\s*10\b", low):
                    try: pain_vals.append(int(m.group(1)))
                    except ValueError: pass
                for m in re.finditer(r"\b(?:cervical|lumbar|thoracic)?\s*(?:rom|range of motion)?[^.;\n]{0,40}(\d+\s*deg(?:ree|rees)?)", fact, re.IGNORECASE):
                    rom_vals.append(m.group(1).replace("degrees", "deg").replace("degree", "deg"))
                for m in re.finditer(r"\b([0-5](?:\.\d+)?\s*/\s*5)\b", fact, re.IGNORECASE):
                    strength_vals.append(m.group(1).replace(" ", ""))
                if re.search(r"\b(plan|continue|follow-?up|home exercise|therapy)\b", low):
                    plan_snips.append(textwrap.shorten(sanitize_for_report(fact), width=250, placeholder="..."))
        if not (pain_vals or rom_vals or strength_vals): continue
        parts = [f"PT evaluation/progression ({region}) with {len(items)} sessions this week."]
        if pain_vals: parts.append(f"Pain scores {min(pain_vals)}/10 to {max(pain_vals)}/10.")
        if rom_vals: parts.append(f"ROM values include {', '.join(sorted(set(rom_vals))[:3])}.")
        if strength_vals: parts.append(f"Strength values include {', '.join(sorted(set(strength_vals))[:3])}.")
        parts.append(f"Plan: {plan_snips[0]}" if plan_snips else "Plan: continue therapy and reassess functional status.")
        agg_id_seed = "|".join(sorted(i.event_id for i in items))
        aggregated.append(ChronologyProjectionEntry(
            event_id=f"ptw_{hashlib.sha1(agg_id_seed.encode('utf-8')).hexdigest()[:14]}",
            date_display=_iso_date_display(week_start), provider_display=provider, event_type_display="Therapy Visit",
            patient_label=patient, facts=[" ".join(parts)], citation_display=", ".join(sorted(citations)[:8]) if citations else items[0].citation_display,
            confidence=max(i.confidence for i in items)
        ))
    return passthrough + aggregated

def _apply_timeline_selection(entries: list[ChronologyProjectionEntry], *, total_pages: int = 0, selection_meta: dict[str, Any] | None = None) -> list[ChronologyProjectionEntry]:
    if not entries: return entries
    entries = _split_composite_entries(entries, total_pages)
    entries = _aggregate_pt_weekly_rows(entries, total_pages)
    entries = _collapse_repetitive_entries(entries)
    grouped: dict[str, list[ChronologyProjectionEntry]] = defaultdict(list)
    for entry in entries: grouped[entry.patient_label].append(entry)
    selected, selected_utility_components, delta_u_trace, stopping_reason, selected_ids_global = [], [], [], "no_candidates", set()
    for patient_label in sorted(grouped.keys()):
        rows = grouped[patient_label]
        scored, seen_payload = [], set()
        for row in rows:
            event_class = _classify_projection_entry(row)
            score = _projection_entry_score(row)
            if "date not documented" in (row.date_display or "").lower() and event_class in {"clinic", "other", "labs", "questionnaire", "vitals"} and score < 70: continue
            dedupe_key = (row.date_display, event_class, " ".join(f.strip().lower() for f in row.facts[:2]))
            if dedupe_key in seen_payload: score = max(0, score - 20)
            else: seen_payload.add(dedupe_key)
            row.confidence = max(0, min(100, score))
            scored.append((score, event_class, row))
        substantive = [(s, c, r) for (s, c, r) in scored if _is_substantive_entry(r) and _event_has_renderable_snippet(r) and c not in {"admin", "vitals", "questionnaire"}]
        if not substantive: continue
        present_buckets = sorted({b for _, _, row in substantive for b in [_bucket_for_required_coverage(row)] if b is not None})
        selected_patient, selected_ids_patient, selected_base_ids_patient, token_cache = [], set(), set(), {row.event_id: _entry_novelty_tokens(row) for _, _, row in substantive}
        for bucket in present_buckets:
            candidates = [(score, cls, row) for score, cls, row in substantive if row.event_id not in selected_ids_patient and _bucket_for_required_coverage(row) == bucket]
            if not candidates: continue
            candidates.sort(key=lambda item: (-item[0], item[2].date_display, item[2].event_id))
            chosen = candidates[0][2]; selected_patient.append(chosen); selected_ids_patient.add(chosen.event_id); selected_base_ids_patient.add(chosen.event_id.split("::", 1)[0]); selected_ids_global.add(chosen.event_id)
            selected_utility_components.append({"event_id": chosen.event_id, "patient_label": patient_label, "bucket": bucket, "utility": 1.0, "delta_u": 1.0, "components": {"substance": round(min(1.0, _entry_substance_score(chosen) / 10.0), 4), "bucket_bonus": 1.0, "temporal_gain": 1.0 if len(selected_patient) == 1 else 0.5, "novelty_gain": 1.0, "redundancy_penalty": 0.0, "noise_penalty": 0.0}, "forced_bucket": True})
            delta_u_trace.append(1.0)
        low_delta_streak, covered_buckets = 0, {b for row in selected_patient for b in [_bucket_for_required_coverage(row)] if b}
        remaining = [(score, cls, row) for score, cls, row in substantive if row.event_id not in selected_ids_patient]
        while remaining and len(selected_patient) < SELECTION_HARD_MAX_ROWS:
            selected_dates = [d for d in (_entry_date_only(r) for r in selected_patient) if d is not None]
            best_idx, best_utility, best_payload = -1, -1.0, {}
            for idx, (score, _cls, row) in enumerate(remaining):
                bucket = _bucket_for_required_coverage(row); row_base = row.event_id.split("::", 1)[0]
                if bucket == "procedure" and row_base in selected_base_ids_patient: continue
                substance_comp = min(1.0, _entry_substance_score(row) / 10.0); bucket_comp = 1.0 if bucket and bucket in present_buckets and bucket not in covered_buckets else 0.0
                temporal_comp = _temporal_coverage_gain(row, selected_dates); novelty_comp = _novelty_gain(row, selected_patient, token_cache); redundancy_comp = _redundancy_penalty(row, selected_patient, token_cache); noise_comp = 1.0 if _is_flowsheet_noise(" ".join(row.facts)) else 0.0
                utility = (0.45 * substance_comp + 0.25 * bucket_comp + 0.20 * temporal_comp + 0.20 * novelty_comp - 0.20 * redundancy_comp - 0.20 * noise_comp)
                if _classify_projection_entry(row) == "labs" and not re.search(r"\b(h|l|high|low|critical|panic|elevated|depressed|abnormal|>|<)\b", " ".join(row.facts).lower()): utility -= 0.4
                if utility > best_utility or (abs(utility - best_utility) < 1e-9 and (row.date_display, row.event_id) < (remaining[best_idx][2].date_display, remaining[best_idx][2].event_id)):
                    best_idx, best_utility = idx, utility
                    best_payload = {"substance": round(substance_comp, 4), "bucket_bonus": round(bucket_comp, 4), "temporal_gain": round(temporal_comp, 4), "novelty_gain": round(novelty_comp, 4), "redundancy_penalty": round(redundancy_comp, 4), "noise_penalty": round(noise_comp, 4)}
            if best_idx < 0: stopping_reason = "no_candidates"; break
            score, _cls, chosen = remaining.pop(best_idx); delta_u = round(best_utility, 6); delta_u_trace.append(delta_u)
            low_delta_streak = low_delta_streak + 1 if delta_u < UTILITY_EPSILON else 0
            selected_patient.append(chosen); selected_ids_patient.add(chosen.event_id); selected_base_ids_patient.add(chosen.event_id.split("::", 1)[0]); selected_ids_global.add(chosen.event_id)
            chosen_bucket = _bucket_for_required_coverage(chosen)
            if chosen_bucket:
                covered_buckets.add(chosen_bucket)
            selected_utility_components.append({"event_id": chosen.event_id, "patient_label": patient_label, "bucket": chosen_bucket, "utility": round(best_utility, 6), "delta_u": delta_u, "components": best_payload, "forced_bucket": False})
            if covered_buckets.issuperset(present_buckets) and low_delta_streak >= (UTILITY_CONSECUTIVE_LOW_K * 2 if total_pages > 300 else UTILITY_CONSECUTIVE_LOW_K): stopping_reason = "saturation"; break
            if len(selected_patient) >= SELECTION_HARD_MAX_ROWS: stopping_reason = "safety_fuse"; break
        proc_by_date, compact_main = defaultdict(list), []
        main = [(next((s for s, _c, r in scored if r.event_id == row.event_id), 0), _classify_projection_entry(row), row) for row in selected_patient]
        for item in main:
            score, cls, row = item
            if cls != "surgery_procedure": compact_main.append(item); continue
            m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", row.date_display or ""); key = m.group(1) if m else row.date_display; proc_by_date[key].append(item)
        for key in sorted(proc_by_date.keys()):
            items = proc_by_date[key]; items.sort(key=lambda it: (-it[0], it[2].event_id)); top = items[0]
            merged_facts, seen_facts, merged_cites = [], set(), set()
            for _, _, row in items:
                merged_cites.update(part.strip() for part in (row.citation_display or "").split(",") if part.strip())
                for fact in row.facts:
                    nf = fact.strip().lower()
                    if not nf or nf in seen_facts: continue
                    seen_facts.add(nf); merged_facts.append(fact)
            top_row = top[2]; compact_main.append((top[0], top[1], ChronologyProjectionEntry(event_id=top_row.event_id, date_display=top_row.date_display, provider_display=top_row.provider_display, event_type_display=top_row.event_type_display, patient_label=top_row.patient_label, facts=merged_facts[:6] if merged_facts else top_row.facts, citation_display=", ".join(sorted(merged_cites)) if merged_cites else top_row.citation_display, confidence=top_row.confidence)))
        main = compact_main; main.sort(key=lambda item: (item[2].date_display, -item[0], item[2].event_id)); seen_main_ids = set()
        for _, _, row in main:
            if row.event_id in seen_main_ids: continue
            seen_main_ids.add(row.event_id); selected.append(row)
    if not stopping_reason and selected: stopping_reason = "all_buckets_covered"
    if selection_meta is not None: selection_meta.update({"selected_utility_components": selected_utility_components, "stopping_reason": stopping_reason if selected else "no_candidates", "delta_u_trace": delta_u_trace[-50:], "hard_max_rows": SELECTION_HARD_MAX_ROWS})
    return selected

def _merge_projection_entries(entries: list[ChronologyProjectionEntry], select_timeline: bool = True) -> list[ChronologyProjectionEntry]:
    deduped, seen_identity = [], set()
    for entry in entries:
        ident = (entry.event_id, entry.patient_label, entry.date_display, entry.event_type_display)
        if ident in seen_identity: continue
        seen_identity.add(ident); deduped.append(entry)
    grouped = {}
    for entry in deduped:
        if (entry.date_display or "").strip().lower() == "date not documented" or not select_timeline: key = (entry.patient_label, entry.date_display, entry.event_type_display, entry.event_id)
        else: key = (entry.patient_label, entry.date_display, entry.event_type_display, entry.provider_display)
        grouped.setdefault(key, []).append(entry)
    merged, type_rank = [], {"Hospital Admission": 1, "Emergency Visit": 2, "Procedure/Surgery": 3, "Imaging Study": 4, "Hospital Discharge": 5, "Discharge": 6, "Inpatient Progress": 7, "Follow-Up Visit": 8, "Therapy Visit": 9, "Lab Result": 10}
    for key in sorted(grouped.keys(), key=lambda k: (k[0], k[1])):
        group = grouped[key]
        if len(group) == 1: merged.append(group[0]); continue
        all_ids = sorted({g.event_id for g in group}); event_id = hashlib.sha1("|".join(all_ids).encode("utf-8")).hexdigest()[:16]
        facts, seen_facts, citations, provider_counts, event_types = [], set(), [], {}, []
        for g in group:
            provider_counts[g.provider_display] = provider_counts.get(g.provider_display, 0) + 1; event_types.append(g.event_type_display)
            for fact in g.facts:
                norm = fact.strip().lower()
                if norm and norm not in seen_facts: facts.append(fact); seen_facts.add(norm)
                if len(facts) >= 4: break
            if g.citation_display: citations.extend([part.strip() for part in g.citation_display.split(",") if part.strip()])
        merged_citations = ", ".join(sorted(set(citations))[:6]); provider_display = sorted(provider_counts.items(), key=lambda item: (item[0] == "Unknown", -item[1], item[0]))[0][0]; event_type_display = sorted(event_types, key=lambda et: (type_rank.get(et, 99), et))[0]
        merged.append(ChronologyProjectionEntry(event_id=event_id, date_display=key[1], provider_display=provider_display, event_type_display=event_type_display, patient_label=key[0], facts=facts if not select_timeline else facts[:4], citation_display=merged_citations, confidence=max(g.confidence for g in group)))
    def _entry_date_key(entry: ChronologyProjectionEntry) -> tuple[int, str]:
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", entry.date_display)
        return (0, m.group(1)) if m else (99, "9999-12-31")
    if select_timeline: merged = _apply_timeline_selection(merged)
    return sorted(merged, key=lambda e: (e.patient_label, _entry_date_key(e), e.event_id))

def build_chronology_projection(events: list[Event], providers: list[Provider], page_map: dict[int, tuple[str, int]] | None = None, page_patient_labels: dict[int, str] | None = None, page_text_by_number: dict[int, str] | None = None, debug_sink: list[dict] | None = None, select_timeline: bool = True, selection_meta: dict | None = None) -> ChronologyProjection:
    entries = []; sorted_events = sorted(events, key=lambda e: e.date.sort_key() if e.date else (99, "UNKNOWN"))
    provider_dated_pages = {}
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
        if not event.provider_id or event.provider_id not in provider_dated_pages: inferred_from_provider = None
        else:
            pages = sorted(set(event.source_page_numbers))
            if not pages: inferred_from_provider = None
            else:
                candidates = []
                for source_page, source_date in provider_dated_pages[event.provider_id]:
                    min_dist = min(abs(p - source_page) for p in pages)
                    if min_dist <= 2: candidates.append((min_dist, source_date))
                inferred_from_provider = sorted(candidates, key=lambda item: (item[0], item[1].isoformat()))[0][1] if candidates else None
        if inferred_from_provider is not None: return inferred_from_provider
        if not page_text_by_number: return None
        page_dates = []
        for p in sorted(set(event.source_page_numbers)):
            text = page_text_by_number.get(p, "")
            if not text:
                continue
            for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)(?:\b|T)", text):
                try:
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    if date_sanity(d):
                        page_dates.append(d)
                except ValueError:
                    continue
            for m in re.finditer(r"\b([01]?\d)/([0-3]?\d)/(19[7-9]\d|20\d{2})\b", text):
                try:
                    d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
                    if date_sanity(d):
                        page_dates.append(d)
                except ValueError:
                    continue
        return sorted(page_dates)[0] if page_dates else None
    for event in sorted_events:
        facts, joined_raw = [], " ".join(f.text for f in event.facts if f.text)
        low_joined_raw = joined_raw.lower()
        if _is_flowsheet_noise(joined_raw):
            if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "flowsheet_noise", "provider_id": event.provider_id})
            continue
        if select_timeline:
            if not surgery_classifier_guard(event):
                if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "surgery_guard", "provider_id": event.provider_id})
                continue
            if event.event_type.value == "referenced_prior_event":
                if not re.search(r"\b(impression|assessment|diagnosis|initial evaluation|physical therapy|pt eval|rom|range of motion|strength|work status|work restriction|clinical impression|mri|x-?ray|fluoroscopy|depo-?medrol|lidocaine|epidural|esi)\b", low_joined_raw):
                    if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "referenced_noise", "provider_id": event.provider_id})
                    continue
            high_value = _is_high_value_event(event, joined_raw)
            if (not event.date or not event.date.value) and not high_value:
                if page_text_by_number and len(page_text_by_number) > 300 and _is_substantive_event(event): pass
                else:
                    if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "undated_low_value", "provider_id": event.provider_id})
                    continue
            if (not event.date or not event.date.value) and event.event_type.value in {"office_visit", "pt_visit", "inpatient_daily_note"}:
                strong_undated = bool(re.search(r"\b(diagnosis|assessment|impression|problem|fracture|tear|infection|debridement|orif|procedure|injection|mri|x-?ray|fluoroscopy|depo-?medrol|lidocaine|pain\s*\d)\b", low_joined_raw))
                if not strong_undated:
                    if page_text_by_number and len(page_text_by_number) > 300 and _is_substantive_event(event): pass
                    else:
                        if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "undated_low_value", "provider_id": event.provider_id})
                        continue
        inferred_date = infer_date(event) if not event.date or not event.date.value else None
        eff_date = event.date.value if event.date and event.date.value and isinstance(event.date.value, date) and date_sanity(event.date.value) else inferred_date
        if select_timeline:
            for fact in event.facts:
                if fact.technical_noise or not is_reportable_fact(fact.text): continue
                cleaned = sanitize_for_report(fact.text)
                if is_noise_span(cleaned) and not re.search(r"\b(assessment|diagnosis|impression|plan|fracture|tear|infection|pain|rom|strength|procedure|injection|mri|x-?ray|follow-?up|therapy)\b", cleaned.lower()): continue
                if _is_header_noise_fact(cleaned): continue
                low_cleaned = cleaned.lower()
                if "labs found:" in low_cleaned and not re.search(r"\b(h|l|high|low|critical|panic|elevated|depressed|abnormal|>|<)\b", low_cleaned): continue
                if re.search(r"\b(tobacco status|never smoked|smokeless tobacco|weight percentile|body height|body weight|head occipital-frontal circumference)\b", low_cleaned): continue
                if not _fact_temporally_consistent(cleaned, eff_date):
                    if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "fact_date_mismatch", "provider_id": event.provider_id})
                    continue
                cleaned = _strip_conflicting_timestamps(cleaned, eff_date)
                if len(cleaned) > 280: cleaned = textwrap.shorten(cleaned, width=280, placeholder="...")
                if _is_vitals_heavy(cleaned): continue
                low_fact = cleaned.lower(); severe_score = False
                if re.search(r"\b(phq-?9|gad-?7|pain interference|questionnaire|survey score|score)\b", low_fact):
                    m = re.search(r"\b(phq-?9|gad-?7)\s*[:=]?\s*(\d{1,2})\b", low_fact)
                    if m and int(m.group(2)) >= 15:
                        severe_score = True
                    if not severe_score:
                        continue
                facts.append(cleaned)
                if len(facts) >= (8 if (page_text_by_number and len(page_text_by_number) > 300) else 3):
                    break
        else:
            for fact in event.facts:
                if fact.technical_noise or not fact.text:
                    continue
                cleaned = sanitize_for_report(fact.text)
                if _is_header_noise_fact(cleaned):
                    continue
                if is_noise_span(cleaned) and not re.search(r"\b(diagnosis|impression|fracture|tear|infection|rom|strength|procedure|injection|mri|x-?ray|follow-?up|therapy|medication|treatment)\b", cleaned.lower()):
                    continue
                facts.append(cleaned)
        if select_timeline and page_text_by_number and len(page_text_by_number) > 300:
            if event.event_type.value == "pt_visit" or re.search(r"\b(physical therapy|pt eval|range of motion|rom|strength)\b", low_joined_raw):
                for ptf in _extract_pt_elements(joined_raw):
                    if ptf.lower() not in {f.lower() for f in facts}:
                        facts.append(ptf)
            if event.event_type.value == "imaging_study" or re.search(r"\b(mri|x-?ray|radiology|impression)\b", low_joined_raw):
                for imf in _extract_imaging_elements(joined_raw):
                    if imf.lower() not in {f.lower() for f in facts}:
                        facts.append(imf)
            facts = facts[:10]
        if not facts:
            if debug_sink is not None:
                debug_sink.append({"event_id": event.event_id, "reason": "low_substance", "provider_id": event.provider_id})
            continue
        date_display = _projection_date_display(event) if event.date and event.date.value else (_iso_date_display(inferred_date) if inferred_date else "Date not documented")
        citation_display = _citation_display(event, page_map)
        if not citation_display and select_timeline:
            if debug_sink is not None: debug_sink.append({"event_id": event.event_id, "reason": "no_citation", "provider_id": event.provider_id})
            continue
        citation_display = citation_display or "Source record not documented"
        event_type_display = "Emergency Visit" if (re.search(r"\b(emergency department|emergency room|ed visit|er visit|chief complaint)\b", low_joined_raw) and not re.search(r"\b(intake questionnaire|patient intake|intake form|new patient)\b", low_joined_raw)) else ("Procedure/Surgery" if re.search(r"\b(epidural|esi|injection|procedure|fluoroscopy|depo-?medrol|lidocaine|interlaminar|transforaminal)\b", low_joined_raw) else ("Imaging Study" if re.search(r"\b(mri|x-?ray|radiology|impression:)\b", low_joined_raw) else ("Therapy Visit" if re.search(r"\b(physical therapy|pt eval|initial evaluation|rom|range of motion|strength)\b", low_joined_raw) else ("Orthopedic Consult" if re.search(r"\b(orthopedic|ortho consult|orthopaedic)\b", low_joined_raw) else ("Clinical Note" if event.event_type.value == "inpatient_daily_note" and not INPATIENT_MARKER_RE.search(" ".join(facts)) else _event_type_display(event))))))
        entries.append(ChronologyProjectionEntry(event_id=event.event_id, date_display=date_display, provider_display=_provider_name(event, providers), event_type_display=event_type_display, patient_label=_event_patient_label(event, page_patient_labels), facts=facts, citation_display=citation_display, confidence=event.confidence))

    def _line_snippets(text: str, pattern: str, limit: int = 2) -> list[str]:
        out = []
        for line in re.split(r"[\r\n]+", text or ""):
            line = sanitize_for_report(line).strip()
            if not line or not re.search(pattern, line, re.IGNORECASE): continue
            if re.fullmatch(r"(chief complaint|hpi|history of present illness|impression|assessment|plan)\.?", line, re.IGNORECASE): continue
            out.append(line)
            if len(out) >= limit: break
        return out

    if select_timeline and page_text_by_number:
        if not any(e.event_type_display == "Procedure/Surgery" for e in entries):
            hit_pages, inf_dates = [], []
            for p in sorted(page_text_by_number.keys()):
                txt = (page_text_by_number.get(p) or "").lower()
                if not txt or sum(1 for mk in ["fluoroscopy", "depo-medrol", "lidocaine", "complications:", "interlaminar", "transforaminal"] if mk in txt) < 2: continue
                hit_pages.append(p)
                for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)\b", txt):
                    try:
                        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                        if date_sanity(d):
                            inf_dates.append(d)
                    except ValueError:
                        continue
            if hit_pages:
                proc_date = sorted(inf_dates)[0] if inf_dates else None
                proc_facts = []
                for p in hit_pages[:5]:
                    proc_facts.extend(_line_snippets(page_text_by_number.get(p) or "", r"(interlaminar|transforaminal|epidural|fluoroscopy|depo-?medrol|lidocaine|complications?)", limit=3))
                entries.append(ChronologyProjectionEntry(event_id=f"proc_anchor_{hashlib.sha1('|'.join(map(str, hit_pages)).encode('utf-8')).hexdigest()[:12]}", date_display=_iso_date_display(proc_date) if proc_date else "Date not documented", provider_display="Unknown", event_type_display="Procedure/Surgery", patient_label="See Patient Header", facts=proc_facts[:4] or ["Epidural steroid injection documented."], citation_display=", ".join(f"p. {p}" for p in hit_pages[:5]), confidence=85))

    if select_timeline:
        merged_entries = sorted(_apply_timeline_selection(entries, total_pages=len(page_text_by_number or {}), selection_meta=selection_meta), key=lambda e: (e.patient_label, (re.search(r"\b(\d{4}-\d{2}-\d{2})\b", e.date_display).group(1) if re.search(r"\b(\d{4}-\d{2}-\d{2})\b", e.date_display) else "9999-12-31"), e.event_id))
    else:
        merged_entries = _merge_projection_entries(entries, select_timeline=select_timeline)

    if selection_meta is not None:
        selection_meta.update(asdict(SelectionResult(
            extracted_event_ids=[e.event_id for e in sorted_events],
            candidates_initial_ids=[e.event_id for e in entries],
            candidates_after_backfill_ids=[e.event_id for e in entries],
            kept_ids=[e.event_id for e in merged_entries],
            final_ids=[e.event_id for e in merged_entries],
            stopping_reason=str(selection_meta.get("stopping_reason", "no_candidates")),
            delta_u_trace=list(selection_meta.get("delta_u_trace", [])),
            selected_utility_components=list(selection_meta.get("selected_utility_components", []))
        )))
    return ChronologyProjection(generated_at=datetime.now(timezone.utc), entries=merged_entries, select_timeline=select_timeline)

@dataclass
class SelectionResult:
    extracted_event_ids: list[str]
    candidates_initial_ids: list[str]
    candidates_after_backfill_ids: list[str]
    kept_ids: list[str]
    final_ids: list[str]
    stopping_reason: str = "no_candidates"
    delta_u_trace: list[float] | None = None
    selected_utility_components: list[dict[str, Any]] | None = None
