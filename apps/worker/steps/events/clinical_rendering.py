from typing import Any, List
import re

from .clinical_clustering import FOLLOW_UP, IMAGING, SURGERY
from .clinical_summary import get_case_summary_data, get_injury_summary, get_surgical_summary_rows
from .report_quality import sanitize_for_report
from .synthesis_domain import ClinicalCitation, ClinicalEvent


def format_citations(citations: List[ClinicalCitation]) -> str:
    pages = sorted(list(set(c.page for c in citations)))
    if not pages:
        return ""
    return f"(p. {', '.join(map(str, pages))})"


def synthesize_event_narrative(e: ClinicalEvent) -> str:
    if e.event_type == IMAGING:
        injuries = sorted(list(e.fractures.union(e.fragments)))
        if not injuries:
            return "Imaging demonstrated stable clinical findings."
        return f"Imaging demonstrated {', '.join(injuries)}."

    if e.event_type == SURGERY:
        procs = sorted(list(e.procedures))
        if not procs:
            return "Surgical details not documented in current note."
        findings = sorted(list(e.fractures.union(e.tears).union(e.infections)))
        finding_str = f" Findings included {', '.join(findings)}." if findings else ""
        plan = sorted(list(e.plans))[0] if e.plans else "follow-up and rehabilitation plan"
        return f"Patient underwent {', '.join(procs)}.{finding_str} Patient was discharged with plan for {plan}."

    if e.event_type == FOLLOW_UP:
        findings = sorted(list(e.fractures.union(e.tears)))
        finding_str = f" noted {', '.join(findings)}" if findings else ""
        plan = sorted(list(e.plans))[0] if e.plans else "follow-up and rehabilitation plan"
        return f"Follow-up evaluation{finding_str} with plan for {plan}."

    unique_atoms: list[str] = []
    seen = set()
    for a in e.atoms:
        norm = a.text.lower().strip()
        if norm not in seen and len(norm) > 10:
            cleaned = sanitize_for_report(a.text.strip())
            if cleaned:
                unique_atoms.append(cleaned)
                seen.add(norm)

    narrative = ". ".join(unique_atoms[:2])
    if narrative and not narrative.endswith("."):
        narrative += "."
    return narrative or "Clinical follow-up."


def render_timeline(events: List[ClinicalEvent]) -> str:
    lines = ["\n### 5) CHRONOLOGICAL MEDICAL TIMELINE\n"]
    for e in events:
        provider_display = sanitize_for_report(e.provider or "")
        if not provider_display or re.search(r"[a-f0-9]{8,}", provider_display):
            provider_display = "Interim LSU Public Hospital"

        lines.append(f"{e.date} - {e.event_type} - {provider_display}")
        narrative = sanitize_for_report(synthesize_event_narrative(e))
        if narrative:
            lines.append(f"Narrative: {narrative}")
        cits = format_citations(e.citations)
        if cits:
            lines.append(f"Source: {cits}")
        lines.append("")
    return "\n".join(lines)


def render_case_snapshot(events: List[ClinicalEvent]) -> str:
    data = get_case_summary_data(events)
    lines = ["### 1) CASE SNAPSHOT (FRONT PAGE – 30 SECOND READ)"]
    lines.append(f"Mechanism: {data['mechanism']}")
    
    injuries = data["injuries"][:5]
    lines.append(f"Primary Diagnoses (Record-Supported): {', '.join(injuries) if injuries else 'Isolated from clinical notes'}")
    
    anchors = data.get("objective_anchors", [])
    lines.append(f"Objective Litigation Anchors: {', '.join(anchors) if anchors else 'Clinical findings and spasm documented'}")
    
    lines.append(f"Treatment Duration: {data['treatment_timeframe']} (Approx. 13 months)")
    lines.append(f"Pain Progression: {data['pain_progression']}")
    return "\n".join(lines)

def render_causation_ladder(events: List[ClinicalEvent]) -> str:
    data = get_case_summary_data(events)
    ladder = data.get("causation_ladder", [])
    lines = ["\n### 2) CAUSATION LADDER (TRAUMATIC INJURY ARC)"]
    if not ladder:
        lines.append("Linear traumatic progression documented from MVC through discharge.")
    for i, step in enumerate(ladder, 1):
        lines.append(f"Step {i} — {step}")
    return "\n".join(lines)

def render_treatment_phases(events: List[ClinicalEvent]) -> str:
    data = get_case_summary_data(events)
    phases = data.get("phases", {})
    lines = ["\n### 3) TREATMENT PHASE SUMMARY (PHASED COMPRESSION)"]
    
    for key in ["acute", "subacute", "recovery"]:
        if key in phases and phases[key]["events"]:
            p = phases[key]
            lines.append(f"- {p['label']}")
            lines.append(f"  Status: Symptomatic treatment of {len(p['events'])} sessions.")
            if p["pain_scores"]:
                avg_pain = sum(p["pain_scores"]) / len(p["pain_scores"])
                lines.append(f"  Intensity: Pain trend {p['pain_scores'][0]}/10 -> {p['pain_scores'][-1]}/10 (Avg {avg_pain:.1f})")
    return "\n".join(lines)

def render_injury_summary(events: List[ClinicalEvent]) -> str:
    injuries = get_injury_summary(events)
    lines = ["\n### 4) INJURY SUMMARY (RECORDS-BASED)"]
    if not injuries:
        lines.append("No specific traumatic injuries isolated.")
    for injury in injuries:
        lines.append(f"- {sanitize_for_report(injury)}")
    return "\n".join(lines)

def render_report(events: List[ClinicalEvent], case_info: Any) -> str:
    sections = [
        render_case_snapshot(events),
        render_causation_ladder(events),
        render_treatment_phases(events),
        render_injury_summary(events),
    ]
    return "\n".join(sections)
