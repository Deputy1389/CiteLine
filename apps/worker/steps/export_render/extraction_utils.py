"""
Domain-specific extraction helpers for export rendering (DX, PRO, SDOH, Contradictions).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from apps.worker.lib.noise_filter import is_noise_span
from apps.worker.lib.targeted_ontology import canonical_injuries, canonical_disposition
from apps.worker.steps.events.report_quality import sanitize_for_report, date_sanity
from apps.worker.steps.export_render.common import (
    _sanitize_render_sentence,
    _sanitize_citation_display,
    _sanitize_filename_display,
    _is_sdoh_noise,
    _pick_theory_entry,
    _fact_excerpt,
)
from apps.worker.steps.export_render.constants import (
    DX_ALLOWED_SECTION_RE,
    DX_CODE_RE,
    DX_MEDICAL_TERM_RE,
    TOP10_LOW_VALUE_RE,
    MECHANISM_KEYWORD_RE,
)

if TYPE_CHECKING:
    from datetime import date


def _extract_diagnosis_items(entries: list) -> list[str]:
    dx: set[str] = set()
    section_header = re.compile(r"\b(assessment|impression|diagnosis|dx|problem list|icd|a/p|treatment diagnosis|medical diagnosis|primary dx|secondary dx)\b", re.IGNORECASE)
    deny = re.compile(r"\b(encounter:|hospital admission|emergency room admission|general examination|check up|tobacco status|questionnaire|pain interference|mg\b|tablet|capsule|discharge summary only|fax|cover sheet|difficult mission late kind)\b", re.IGNORECASE)
    icd_re = re.compile(r"\b[A-TV-Z][0-9]{2}(?:\.[0-9A-TV-Z]{1,4})?\b")
    english_med_lexicon = {"fracture", "infection", "dislocation", "tear", "sprain", "strain", "radiculopathy", "disc", "protrusion", "degeneration", "pain", "wound", "hypertension", "diabetes", "anxiety", "depression", "neuropathy", "cervical", "lumbar", "thoracic", "shoulder", "knee", "hip", "ankle", "arm", "leg", "impression", "assessment", "diagnosis", "condition", "syndrome", "stenosis", "herniation", "spondylosis"}
    pt_dx_signal = re.compile(r"\b(cervicalgia|lumbago|cervical strain|lumbar strain|thoracic strain|radiculopathy|sciatica|myofascial pain|whiplash|muscle spasm)\b", re.IGNORECASE)
    hard_dx_signal = re.compile(r"\b(fracture|infection|dislocation|tear|sprain|strain|radiculopathy|protrusion|degeneration|neuropathy|stenosis|herniation|spondylosis|icd-?10)\b", re.IGNORECASE)

    def _negated(text: str) -> bool:
        low = text.lower()
        return bool(re.search(r"\b(denies|negative for|without)\b", low) or re.search(r"\bno\s+(?:evidence of\s+)?(?:pain|strain|sprain|radiculopathy|herniation|stenosis|fracture|dislocation)\b", low))

    for entry in entries:
        lines = [sanitize_for_report(f) for f in list(entry.facts or [])]
        lines = [ln for ln in lines if ln]
        for i, line in enumerate(lines):
            low = line.lower()
            capture_window = []
            if section_header.search(low):
                capture_window.append(line)
                for j in range(i + 1, min(len(lines), i + 4)):
                    nxt = lines[j]
                    if re.match(r"^[A-Z][A-Z\s/&-]{4,}$", nxt.strip()) or re.match(r"^[A-Za-z][A-Za-z\s/&-]{2,40}:\s*$", nxt.strip()): break
                    capture_window.append(nxt)
            elif pt_dx_signal.search(low) or icd_re.search(line):
                capture_window.append(line)

            for text in capture_window:
                if not text or is_noise_span(text) or _is_sdoh_noise(text) or deny.search(text) or _negated(text): continue
                if "difficult mission late kind" in text.lower(): continue
                low_txt = text.lower()
                if "discharge summary" in low_txt: continue
                if not (section_header.search(low_txt) or icd_re.search(text) or pt_dx_signal.search(low_txt) or hard_dx_signal.search(low_txt) or DX_MEDICAL_TERM_RE.search(low_txt)): continue
                tokens = re.findall(r"[a-z]+", low_txt)
                if not tokens: continue
                med_hits = sum(1 for t in tokens if t in english_med_lexicon)
                if (med_hits / max(1, len(tokens))) < 0.18 and not icd_re.search(text) and not pt_dx_signal.search(low_txt): continue
                cleaned = _sanitize_render_sentence(text[:180])
                if cleaned: dx.add(cleaned)
    return sorted(dx)[:12]


def _extract_pro_items(entries: list) -> list[str]:
    pro: set[str] = set()
    pro_re = re.compile(r"\b(phq-?9|gad-?7|promis|oswestry|ndi|sf-?12|sf-?36|eq-?5d|pain interference|pain intensity|pain severity)\b", re.IGNORECASE)
    phrasing_re = re.compile(r"\b(what number best describes|during the past week).{0,80}\b(interfere|interfered|pain)\b", re.IGNORECASE)
    for entry in entries:
        for fact in entry.facts:
            text = sanitize_for_report(fact)
            if text and (pro_re.search(text) or phrasing_re.search(text)):
                cleaned = _sanitize_render_sentence(text[:160])
                if len(cleaned) >= 8 and not re.search(r"\b[a-z]\.$", cleaned, re.IGNORECASE): pro.add(cleaned)
    return sorted(pro)[:12]


def _extract_sdoh_items(entries: list) -> list[str]:
    sdoh: set[str] = set()
    for entry in entries:
        for fact in entry.facts:
            text = sanitize_for_report(fact)
            if text and _is_sdoh_noise(text):
                cleaned = _sanitize_render_sentence(text[:160])
                if len(cleaned) >= 8 and not re.search(r"\b[a-z]\.$", cleaned, re.IGNORECASE): sdoh.add(cleaned)
    return sorted(sdoh)[:20]


def _contradiction_flags(entries: list) -> list[str]:
    flags: list[str] = []
    by_patient: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    smoke_state: dict[str, set[str]] = defaultdict(set)
    nka_state: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        facts = " ".join(entry.facts).lower()
        laterality = set()
        if re.search(r"\bleft\b", facts): laterality.add("left")
        if re.search(r"\bright\b", facts): laterality.add("right")
        if laterality:
            for cond in ("shoulder", "knee", "hip", "arm", "leg", "wrist", "ankle", "fracture", "tear", "wound"):
                if cond in facts: by_patient[entry.patient_label][cond].update(laterality)
        if re.search(r"\bnever smoked|non-smoker|nonsmoker\b", facts): smoke_state[entry.patient_label].add("never")
        if re.search(r"\bcurrent smoker|smokes daily|tobacco use\b", facts): smoke_state[entry.patient_label].add("current")
        if re.search(r"\bno known allergies|nka\b", facts): nka_state[entry.patient_label].add("none")
        if re.search(r"\ballergy to|allergic to\b", facts): nka_state[entry.patient_label].add("allergy_listed")
    for patient, conds in by_patient.items():
        for cond, sides in conds.items():
            if {"left", "right"}.issubset(sides): flags.append(f"{patient}: conflicting laterality documented for {cond} (left and right).")
    for patient, vals in smoke_state.items():
        if {"never", "current"}.issubset(vals): flags.append(f"{patient}: smoking status contradiction (never-smoker vs current smoker).")
    for patient, vals in nka_state.items():
        if {"none", "allergy_listed"}.issubset(vals): flags.append(f"{patient}: allergy contradiction (NKA and listed allergy documented).")
    return flags[:10]


def _repair_case_summary_narrative(
    narrative: str | None,
    *,
    page_text_by_number: dict[int, str] | None,
    page_map: dict[int, tuple[str, int]] | None,
    care_window_start: date | None = None,
    care_window_end: date | None = None,
    projection_entries: list | None = None,
) -> str | None:
    if not narrative:
        return narrative
    incident = _scan_incident_signal(page_text_by_number, page_map)
    lines = narrative.splitlines()
    out: list[str] = []
    saw_doi = False
    saw_mech = False
    for line in lines:
        low = line.lower().strip()
        if low.startswith("date of injury:"):
            saw_doi = True
            if incident.get("found") and incident.get("doi"):
                out.append(f"Date of Injury: {incident['doi']}")
            else:
                out.append("Date of Injury: Not established from records")
            continue
        if low.startswith("mechanism:"):
            saw_mech = True
            if incident.get("found") and incident.get("mechanism"):
                out.append(f"Mechanism: {incident['mechanism']}")
            else:
                out.append("Mechanism: Not established from records")
            continue
        if low.startswith("treatment timeframe:") and care_window_start and care_window_end:
            out.append(f"Treatment Timeframe: {care_window_start} to {care_window_end}")
            continue
        out.append(line)
    if incident.get("found") and incident.get("citation"):
        out.append(f"Incident Citation(s): {incident['citation']}")
    elif incident.get("searched"):
        out.append(f"Incident Search Scope: {incident['searched']}")
    if not saw_doi and incident.get("found") and incident.get("doi"):
        out.append(f"Date of Injury: {incident['doi']}")
    if not saw_mech and incident.get("found") and incident.get("mechanism"):
        out.append(f"Mechanism: {incident['mechanism']}")
    
    anchored_primary: list[str] = []
    anchored_injury_summary: list[str] = []
    
    if projection_entries:
        anchors: dict[str, set[str]] = defaultdict(set)
        for entry in projection_entries:
            facts = list(getattr(entry, "facts", []) or [])
            citation = str(getattr(entry, "citation_display", "") or "").strip()
            for label in canonical_injuries(facts):
                if citation:
                    anchors[label].add(citation)
        high_risk_terms = {"fracture", "dislocation", "wound infection", "infection", "tear"}
        anchored_hard = sorted([k for k, cites in anchors.items() if len(cites) >= 2 or k in high_risk_terms and len(cites) >= 2])
        soft_terms = {"neck pain", "low back pain", "back pain", "cervical radiculopathy", "lumbar radiculopathy", "disc protrusion", "disc herniation"}
        anchored_soft = sorted([k for k, cites in anchors.items() if k in soft_terms and len(cites) >= 2])
        anchored_primary = sorted(dict.fromkeys(anchored_hard + anchored_soft))
        anchored_soft_relaxed = sorted([k for k, cites in anchors.items() if k in soft_terms and len(cites) >= 1])
        anchored_injury_summary = sorted(dict.fromkeys(anchored_hard + anchored_soft_relaxed))
        if anchored_primary and any(l.lower().startswith("primary injuries: not stated") for l in out):
            out = [
                (f"Primary Injuries: {', '.join(anchored_primary[:5])}" if l.lower().startswith("primary injuries:") else l)
                for l in out
            ]
        if anchored_injury_summary:
            out = [
                (f"Injury Summary: {', '.join(anchored_injury_summary[:5]).capitalize()}." if l.lower().strip() == "no specific injuries isolated." else l)
                for l in out
            ]

    if projection_entries:
        operative_count, interventional_count = _procedure_counts(projection_entries)
        updated: list[str] = []
        saw_total = False
        saw_interventional = False
        saw_injury_summary = False
        for line in out:
            low = line.lower().strip()
            if low.startswith("primary injuries:"):
                if anchored_primary:
                    refined = _refine_primary_injuries(anchored_primary, projection_entries)
                    updated.append(f"Primary Injuries: {', '.join(refined) if refined else 'Not established from records'}")
                else:
                    updated.append("Primary Injuries: Not established from records")
                continue
            if low.startswith("injury summary:"):
                saw_injury_summary = True
                if anchored_injury_summary:
                    refined = _refine_primary_injuries(anchored_injury_summary, projection_entries)
                    if refined: updated.append(f"Injury Summary: {', '.join(refined)}.")
                    else: updated.append("Injury Summary: No specific injuries isolated.")
                else:
                    updated.append(line)
                continue
            if low.startswith("total surgeries:"):
                saw_total = True
                updated.append(f"Total Surgeries: {operative_count}")
                continue
            if low.startswith("total interventional procedures:"):
                saw_interventional = True
                updated.append(f"Total Interventional Procedures: {interventional_count}")
                continue
            if low == "no surgeries documented.": continue
            updated.append(line)
        if not saw_total: updated.append(f"Total Surgeries: {operative_count}")
        if interventional_count > 0 and not saw_interventional: updated.append(f"Total Interventional Procedures: {interventional_count}")
        if not saw_injury_summary:
            refined = _refine_primary_injuries(anchored_injury_summary, projection_entries) if anchored_injury_summary else []
            updated.append(f"Injury Summary: {', '.join(refined)}." if refined else "Injury Summary: No specific injuries isolated.")
        if operative_count == 0 and interventional_count > 0: updated.append("No operative surgeries documented.")
        out = updated
    if care_window_start and care_window_end and not any(l.lower().startswith("treatment timeframe:") for l in out):
        out.append(f"Treatment Timeframe: {care_window_start} to {care_window_end}")

    lower_out = "\n".join(out).lower()
    if projection_entries and (
        "liability facts" not in lower_out or "causation chain" not in lower_out or "damages progression" not in lower_out
    ):
        cited_entries = [e for e in projection_entries if (getattr(e, "citation_display", "") or "").strip()]
        if cited_entries:
            liab = _pick_theory_entry(cited_entries, r"\b(mva|mvc|motor vehicle|rear[- ]end|collision|accident|fall|slip)\b", r"\bemergency\b")
            caus = _pick_theory_entry(cited_entries, r"\b(procedure|surgery|injection|epidural|fluoroscopy|impression|mri|ct|x-?ray)\b")
            if caus is liab:
                caus = _pick_theory_entry(cited_entries, r"\b(diagnosis|assessment|radiculopathy|herniation|stenosis|fracture|tear)\b")
            dmg = _pick_theory_entry(cited_entries, r"\b(pain\s*\d+\s*/\s*10|rom|range of motion|strength|work restriction|return to work|therapy)\b")

            liab_excerpt = _fact_excerpt(liab, r"\b(mva|mvc|motor vehicle|rear[- ]end|collision|accident|fall|slip|chief complaint|hpi)\b")
            caus_excerpt = _fact_excerpt(caus, r"\b(impression|diagnosis|procedure|surgery|injection|epidural|fluoroscopy|mri|ct|x-?ray|radiculopathy|herniation|stenosis|fracture|tear)\b")
            dmg_excerpt = _fact_excerpt(dmg, r"\b(pain\s*\d+\s*/\s*10|rom|range of motion|strength|work restriction|return to work|therapy)\b")

            sections = [
                ("Liability Facts", (f"Incident/mechanism is documented in cited records: {liab_excerpt}" if liab_excerpt else "Record evidence documents incident/mechanism context tied to initial treatment presentation."), (getattr(liab, "citation_display", "") or "").strip()),
                ("Causation Chain", (f"Diagnostic/treatment progression supports causation: {caus_excerpt}" if caus_excerpt else "Timeline shows diagnostic and treatment events consistent with injury-driven care progression."), (getattr(caus, "citation_display", "") or "").strip()),
                ("Damages Progression", (f"Symptoms/functional findings document damages progression: {dmg_excerpt}" if dmg_excerpt else "Symptoms and functional findings demonstrate ongoing impact and treatment response over time."), (getattr(dmg, "citation_display", "") or "").strip()),
            ]
            for title, sentence, cite in sections:
                if title.lower() in lower_out: continue
                out.append(f"{title}: {sentence}")
                if cite: out.append(f"Citation(s): {cite}")
    return "\n".join(out)


def _scan_incident_signal(
    page_text_by_number: dict[int, str] | None,
    page_map: dict[int, tuple[str, int]] | None,
) -> dict[str, object]:
    if not page_text_by_number:
        return {"found": False, "doi": None, "mechanism": None, "citation": "", "searched": ""}
    hits: list[tuple[int, str]] = []
    mech_hits: list[tuple[int, str]] = []
    for p in sorted(page_text_by_number.keys()):
        txt = page_text_by_number.get(p) or ""
        low = txt.lower()
        if "emergency" in low and MECHANISM_KEYWORD_RE.search(low): hits.append((p, txt))
        if MECHANISM_KEYWORD_RE.search(low): mech_hits.append((p, txt))
    if not hits and mech_hits: hits = mech_hits[:3]
    if not hits:
        first_pages = sorted(page_text_by_number.keys())[:3]
        searched = []
        for p in first_pages:
            if page_map and p in page_map: searched.append(f"{_sanitize_filename_display(page_map[p][0])} p. {page_map[p][1]}")
            else: searched.append(f"p. {p}")
        return {"found": False, "doi": None, "mechanism": None, "citation": "", "searched": ", ".join(searched)}

    mechanism = None
    for _, txt in hits:
        low = txt.lower()
        if "motor vehicle collision" in low: mechanism = "motor vehicle collision"; break
        if "motor vehicle accident" in low: mechanism = "motor vehicle accident"; break
        if re.search(r"\bmvc\b", low): mechanism = "mvc"; break
        if re.search(r"\bmva\b", low): mechanism = "mva"; break
        if re.search(r"\brear[- ]end\b", low): mechanism = "rear-end collision"; break
        if re.search(r"\bslip(?:ped)?\b|\bfall\b|\bfell\b", low): mechanism = "fall"; break
    if mechanism is None: mechanism = "accident"

    all_dates = []
    for _, txt in hits:
        for m in re.finditer(r"\b(20\d{2}|19[7-9]\d)-([01]\d)-([0-3]\d)\b", txt):
            try: d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError: continue
            if date_sanity(d): all_dates.append(d)
    doi = sorted(all_dates)[0] if all_dates else None

    refs = []
    for p, _ in hits[:3]:
        if page_map and p in page_map: refs.append(f"{_sanitize_filename_display(page_map[p][0])} p. {page_map[p][1]}")
        else: refs.append(f"p. {p}")
    return {"found": True, "doi": doi.isoformat() if doi else None, "mechanism": mechanism, "citation": ", ".join(refs), "searched": ""}


def _procedure_counts(entries: list) -> tuple[int, int]:
    operative_dates: set[str] = set()
    interventional_dates: set[str] = set()
    op_re = re.compile(r"\b(discectomy|fusion|laminectomy|laminotomy|arthroplasty|orif|open reduction|internal fixation|debridement|hardware removal|repair)\b", re.IGNORECASE)
    interventional_re = re.compile(r"\b(epidural|esi|interlaminar|transforaminal|facet injection|trigger point injection|injection|depo-?medrol|lidocaine|fluoroscopy)\b", re.IGNORECASE)
    for e in entries:
        if "procedure" not in (getattr(e, "event_type_display", "") or "").lower(): continue
        blob = " ".join(getattr(e, "facts", []) or "")
        dmatch = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", getattr(e, "date_display", "") or "")
        dkey = dmatch.group(1) if dmatch else str(getattr(e, "event_id", ""))
        if op_re.search(blob): operative_dates.add(dkey)
        elif interventional_re.search(blob): interventional_dates.add(dkey)
    return len(operative_dates), len(interventional_dates)


def _refine_primary_injuries(labels: list[str], entries: list) -> list[str]:
    vals = [re.sub(r"\s+", " ", (x or "").strip().lower()) for x in labels if (x or "").strip()]
    vals = list(dict.fromkeys(vals))
    cmap = {"back pain": "back pain", "low back pain": "low back pain", "neck pain": "neck pain", "cervicalgia": "neck pain (cervicalgia)", "lumbago": "low back pain (lumbago)", "cervical strain": "cervical strain", "lumbar strain": "lumbar strain", "whiplash": "cervical strain (whiplash-associated)", "myofascial pain": "myofascial pain syndrome", "radiculopathy": "radiculopathy", "cervical radiculopathy": "cervical radiculopathy", "lumbar radiculopathy": "lumbar radiculopathy"}
    normalized = list(dict.fromkeys([cmap.get(v, v) for v in vals]))
    if "low back pain" in normalized and "back pain" in normalized: normalized.remove("back pain")
    if "lumbar strain" in normalized and "low back pain" in normalized: normalized.remove("low back pain")
    if "cervical strain" in normalized and "neck pain" in normalized: normalized.remove("neck pain")
    if "cervical strain (whiplash-associated)" in normalized and "neck pain" in normalized: normalized.remove("neck pain")
    if "lumbar radiculopathy" in normalized and "low back pain" in normalized: normalized.remove("low back pain")
    if "cervical radiculopathy" in normalized and "neck pain" in normalized: normalized.remove("neck pain")
    rank = {"cervical strain": 1, "cervical strain (whiplash-associated)": 1, "lumbar strain": 1, "cervical radiculopathy": 2, "lumbar radiculopathy": 2, "radiculopathy": 3, "low back pain": 4, "neck pain": 4, "low back pain (lumbago)": 4, "neck pain (cervicalgia)": 4, "myofascial pain syndrome": 5, "back pain": 6}
    normalized.sort(key=lambda x: (rank.get(x, 50), x))
    return [v[0].upper() + v[1:] if v else v for v in normalized[:6]]
