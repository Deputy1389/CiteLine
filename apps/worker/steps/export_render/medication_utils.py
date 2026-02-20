"""
Medication-specific extraction helpers for export rendering.
"""
from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING

from apps.worker.steps.events.report_quality import sanitize_for_report
from apps.worker.steps.export_render.common import (
    parse_date_string,
    _sanitize_render_sentence,
    _sanitize_citation_display,
)

if TYPE_CHECKING:
    from packages.shared.models import Event


def _extract_med_mentions(text: str) -> list[dict]:
    low = text.lower()
    ingredients = [
        "hydrocodone", "oxycodone", "morphine", "tramadol", "fentanyl",
        "acetaminophen", "ibuprofen", "naproxen", "lisinopril", "metformin",
        "warfarin", "apixaban", "rivaroxaban", "sertraline", "fluoxetine",
        "alprazolam", "diazepam",
    ]
    out: list[dict] = []
    for ing in ingredients:
        if ing not in low:
            continue
        strength = ""
        unit = ""
        for m in re.finditer(rf"{re.escape(ing)}[\s\w/\-]{{0,40}}?(\d+(?:\.\d+)?)\s*mg\b", low):
            strength = m.group(1)
            unit = "mg"
            break
        if not strength:
            for m in re.finditer(rf"{re.escape(ing)}[\s\w/\-]{{0,40}}?(\d+(?:\.\d+)?)\s*mg\s*/\s*ml\b", low):
                strength = m.group(1)
                unit = "mg/ml"
                break
        if not strength:
            for m in re.finditer(rf"(\d+(?:\.\d+)?)\s*mg\b[\s\w/\-]{{0,40}}?{re.escape(ing)}", low):
                strength = m.group(1)
                unit = "mg"
                break
        form_bits: list[str] = []
        if re.search(r"\b(extended release|er|xr|12\s*hr)\b", low):
            form_bits.append("ER")
        if re.search(r"\btablet\b", low):
            form_bits.append("tablet")
        if re.search(r"\bcapsule\b", low):
            form_bits.append("capsule")
        form = "+".join(form_bits) if form_bits else "unspecified"
        label = f"{ing} {strength} mg {form}".strip().replace("  ", " ")
        out.append(
            {
                "ingredient": ing,
                "strength": strength,
                "unit": unit,
                "form": form,
                "label": label,
                "is_opioid": ing in {"hydrocodone", "oxycodone", "morphine", "tramadol", "fentanyl"},
                "parse_confidence": 0.9 if (strength and unit == "mg" and form in {"tablet", "capsule", "ER+tablet", "ER+capsule"}) else 0.5,
            }
        )
    return out


def _extract_medication_changes(entries: list) -> list[str]:
    dated = [(entry, parse_date_string(entry.date_display)) for entry in entries]
    dated = [(e, d) for e, d in dated if d is not None]
    dated.sort(key=lambda x: x[1])
    if len(dated) < 2:
        return []

    changes: list[dict] = []
    seen_any_date = False
    last_by_ing: dict[str, dict] = {}
    last_seen_idx: dict[str, int] = {}
    last_opioids: set[str] = set()
    emitted_direction: set[tuple[date, str, str]] = set()
    plausible_mg_ranges: dict[str, tuple[float, float]] = {
        "acetaminophen": (80.0, 1000.0),
        "hydrocodone": (2.5, 20.0),
        "oxycodone": (2.5, 80.0),
        "morphine": (5.0, 200.0),
        "tramadol": (25.0, 200.0),
        "fentanyl": (12.0, 200.0),
    }
    date_buckets: list[tuple[date, dict[str, dict]]] = []
    change_cue_re = re.compile(
        r"\b(start(?:ed)?|initiated|prescribed|discontinued|stop(?:ped)?|switched|changed to|increased|decreased|titrated|resumed)\b",
        re.IGNORECASE,
    )
    negation_re = re.compile(
        r"\b(not taking|denies taking|allergy|allergic to|intolerance|history of)\b",
        re.IGNORECASE,
    )

    def _add_change(entry_date: date, ingredient: str, category: str, text: str, *, is_opioid: bool = False, parse_confidence: float = 1.0) -> None:
        changes.append({
            "date": entry_date,
            "ingredient": ingredient,
            "category": category,
            "text": _sanitize_render_sentence(text),
            "is_opioid": bool(is_opioid),
            "parse_confidence": float(parse_confidence or 0.0),
        })

    for idx, (entry, entry_date) in enumerate(dated):
        current_mentions: list[dict] = []
        entry_has_change_cue = False
        for fact in entry.facts:
            txt = sanitize_for_report(fact)
            if txt:
                if change_cue_re.search(txt): entry_has_change_cue = True
                if negation_re.search(txt): continue
                current_mentions.extend(_extract_med_mentions(txt))
        current_by_ing: dict[str, dict] = {}
        for med in current_mentions: current_by_ing[med["ingredient"]] = med
        date_buckets.append((entry_date, current_by_ing))
        if not current_mentions:
            seen_any_date = True
            continue

        current_mentions_unique = list(current_by_ing.values())
        current_opioids = {m["ingredient"] for m in current_mentions_unique if m["is_opioid"]}
        continued_opioids = current_opioids & last_opioids
        if last_opioids and current_opioids and current_opioids != last_opioids and entry_has_change_cue:
            if len(last_opioids) == 1 and len(current_opioids) == 1 and not continued_opioids:
                _add_change(entry_date, "__opioid_regimen__", "opioid_regimen_change", f"{entry_date}: Opioid switch detected ({next(iter(sorted(last_opioids)))} -> {next(iter(sorted(current_opioids)))}).", is_opioid=True, parse_confidence=0.9)
            else:
                _add_change(entry_date, "__opioid_regimen__", "opioid_regimen_change", f"{entry_date}: Opioid regimen changed (multiple agents detected; sequence ambiguous).", is_opioid=True, parse_confidence=0.8)

        for med in current_mentions_unique:
            ing = med["ingredient"]
            prev = last_by_ing.get(ing)
            if prev is None and seen_any_date and entry_has_change_cue:
                _add_change(entry_date, ing, "started_stopped", f"{entry_date}: Started {med['label']}.", is_opioid=bool(med.get("is_opioid")), parse_confidence=float(med.get("parse_confidence") or 0.0))
            elif prev is not None:
                try:
                    prev_strength = float(prev["strength"]) if prev.get("strength") else None
                    cur_strength = float(med["strength"]) if med.get("strength") else None
                except ValueError:
                    prev_strength = cur_strength = None
                plausible = plausible_mg_ranges.get(ing)
                in_plausible = bool(plausible and prev_strength is not None and cur_strength is not None and plausible[0] <= prev_strength <= plausible[1] and plausible[0] <= cur_strength <= plausible[1])
                if (prev_strength is not None and cur_strength is not None and prev.get("unit") == med.get("unit") and prev.get("unit") == "mg" and prev.get("form") == med.get("form") and prev.get("is_opioid") and med.get("is_opioid") and float(prev.get("parse_confidence") or 0.0) >= 0.8 and float(med.get("parse_confidence") or 0.0) >= 0.8 and in_plausible and cur_strength != prev_strength and entry_has_change_cue):
                    pct_change = abs(cur_strength - prev_strength) / max(prev_strength, 1.0)
                    direction = "increased" if cur_strength > prev_strength else "decreased"
                    if pct_change >= 0.20:
                        key = (entry_date, ing, direction)
                        opposite = (entry_date, ing, "decreased" if direction == "increased" else "increased")
                        if opposite not in emitted_direction and key not in emitted_direction:
                            emitted_direction.add(key)
                            _add_change(entry_date, ing, "opioid_dose_change", f"{entry_date}: {ing} dose {direction} ({prev_strength:g} mg -> {cur_strength:g} mg).", is_opioid=True, parse_confidence=min(float(prev.get("parse_confidence") or 0.0), float(med.get("parse_confidence") or 0.0)))
                    else:
                        _add_change(entry_date, ing, "strength_changed", f"{entry_date}: {ing} strength variation detected (dose change <20%).", is_opioid=bool(med.get("is_opioid")), parse_confidence=float(med.get("parse_confidence") or 0.0))
                elif prev.get("strength") and med.get("strength") and prev.get("strength") != med.get("strength"):
                    _add_change(entry_date, ing, "strength_changed", f"{entry_date}: {ing} strength/formulation changed (dose not reliably parseable).", is_opioid=bool(med.get("is_opioid")), parse_confidence=float(med.get("parse_confidence") or 0.0))
                if prev.get("form") != med.get("form"):
                    _add_change(entry_date, ing, "formulation_changed", f"{entry_date}: {ing} formulation changed ({prev.get('form', 'unspecified')} -> {med.get('form', 'unspecified')}).", is_opioid=bool(med.get("is_opioid")), parse_confidence=float(med.get("parse_confidence") or 0.0))
            last_by_ing[ing] = med
            last_seen_idx[ing] = idx
        last_opioids = current_opioids if current_opioids else last_opioids
        seen_any_date = True

    total_dates = len(date_buckets)
    for ing, idx in last_seen_idx.items():
        if (total_dates - idx - 1) >= 2:
            stop_date = date_buckets[min(idx + 2, total_dates - 1)][0]
            _add_change(stop_date, ing, "started_stopped", f"{stop_date}: Stopped {ing} (not present in subsequent encounters).", is_opioid=bool((last_by_ing.get(ing) or {}).get("is_opioid")), parse_confidence=float((last_by_ing.get(ing) or {}).get("parse_confidence") or 0.0))

    priority = {"opioid_dose_change": 5, "opioid_regimen_change": 4, "started_stopped": 3, "strength_changed": 2, "formulation_changed": 1}
    best_by_key: dict[tuple[date, str], dict] = {}
    for row in changes:
        if not row.get("text"): continue
        key = (row["date"], row["ingredient"])
        existing = best_by_key.get(key)
        row_prio = priority.get(str(row.get("category") or ""), 0)
        if existing is None:
            best_by_key[key] = row
            continue
        existing_prio = priority.get(str(existing.get("category") or ""), 0)
        if row_prio > existing_prio: best_by_key[key] = row
        elif row_prio == existing_prio and str(row.get("text", "")) < str(existing.get("text", "")): best_by_key[key] = row

    ordered = sorted(best_by_key.values(), key=lambda r: (r["date"], r["ingredient"], r.get("text", "")))
    rendered: list[str] = []
    seen: set[str] = set()
    for row in ordered:
        txt = str(row.get("text") or "")
        if re.search(r"\bdose (increased|decreased)\b", txt, re.IGNORECASE):
            if (not row.get("is_opioid")) or float(row.get("parse_confidence") or 0.0) < 0.8:
                ingredient = str(row.get("ingredient") or "medication")
                txt = f"{row['date']}: {ingredient} strength/formulation changed (dose not reliably parseable)."
        key = txt.lower().strip()
        if key and key not in seen:
            seen.add(key)
            rendered.append(_sanitize_render_sentence(txt))
    return [r for r in rendered if r][:12]


def _extract_medication_change_rows(entries: list) -> list[dict]:
    dated = [(entry, parse_date_string(entry.date_display)) for entry in entries]
    dated = [(e, d) for e, d in dated if d is not None]
    dated.sort(key=lambda x: x[1])
    if len(dated) < 2: return []
    rows: list[dict] = []
    last_opioids: set[str] = set()
    change_cue_re = re.compile(r"\b(start(?:ed)?|initiated|prescribed|discontinued|stop(?:ped)?|switched|changed to|increased|decreased|titrated|resumed)\b", re.IGNORECASE)
    negation_re = re.compile(r"\b(not taking|denies taking|allergy|allergic to|intolerance|history of)\b", re.IGNORECASE)
    for entry, entry_date in dated:
        mentions: list[dict] = []
        entry_has_change_cue = False
        for fact in entry.facts:
            txt = sanitize_for_report(fact)
            if not txt: continue
            if negation_re.search(txt): continue
            if change_cue_re.search(txt): entry_has_change_cue = True
            mentions.extend(_extract_med_mentions(txt))
        if not mentions: continue
        opioid_mentions = [m for m in mentions if m.get("is_opioid")]
        current_opioids = {m["ingredient"] for m in opioid_mentions}
        if last_opioids and current_opioids and current_opioids != last_opioids and entry_has_change_cue:
            continued = current_opioids & last_opioids
            if len(last_opioids) == 1 and len(current_opioids) == 1 and not continued:
                text = f"Opioid switch detected ({next(iter(sorted(last_opioids)))} -> {next(iter(sorted(current_opioids)))})."
            else:
                text = "Opioid regimen changed (multiple agents detected; sequence ambiguous)."
            rows.append({
                "date": entry_date,
                "date_display": entry.date_display,
                "text": text,
                "is_opioid": True,
                "is_regimen_change": True,
                "parse_confidence": max((float(m.get("parse_confidence") or 0.0) for m in opioid_mentions), default=0.0),
                "citation": _sanitize_citation_display((entry.citation_display or "").strip()),
            })
        if current_opioids: last_opioids = current_opioids
    seen: set[tuple[str, str]] = set()
    dedup: list[dict] = []
    for row in rows:
        key = (row["date_display"], row["text"].lower())
        if key in seen: continue
        seen.add(key)
        dedup.append(row)
    return dedup[:12]
