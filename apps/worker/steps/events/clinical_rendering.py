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


def render_case_summary(events: List[ClinicalEvent], case_info: Any) -> str:
    data = get_case_summary_data(events)
    timeframe = data["treatment_timeframe"]
    injury_date = timeframe.split(" -> ")[0] if "->" in timeframe else "Date not documented"
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", injury_date):
        injury_date = "Date not documented"
    injuries = data["injuries"][:5]
    mechanism = data.get("mechanism", "Not established from records")
    if mechanism == "Gunshot wound" and not any("gunshot" in i.lower() or "gsw" in i.lower() for i in injuries):
        mechanism = "Not established from records"
    if mechanism == "Not established from records" or not injuries:
        injury_date = "Not established from records"

    lines = ["### 1) CASE SUMMARY"]
    lines.append(f"Date of Injury: {injury_date if injury_date != 'Date not documented' else 'Not established from records'}")
    lines.append(f"Mechanism: {mechanism}")
    lines.append(f"Primary Injuries: {', '.join(injuries) if injuries else 'Not established from records'}")
    lines.append(f"Total Surgeries: {data['total_surgeries']}")
    lines.append(f"Major Complications: {', '.join(data['complications']) or 'None documented'}")
    lines.append(f"Treatment Timeframe: {timeframe}")
    return "\n".join(lines)


def render_injury_summary(events: List[ClinicalEvent]) -> str:
    injuries = get_injury_summary(events)
    lines = ["\n### 2) INJURY SUMMARY"]
    if not injuries:
        lines.append("No specific injuries isolated.")
    for injury in injuries:
        lines.append(f"- {sanitize_for_report(injury)}")
    return "\n".join(lines)


def render_surgical_summary(events: List[ClinicalEvent]) -> str:
    rows = get_surgical_summary_rows(events)
    lines = ["\n### 3) SURGICAL SUMMARY"]
    if not rows:
        lines.append("No surgeries documented.")
    for row in rows:
        procedures = [sanitize_for_report(p) for p in row["procedures"]]
        procedures = [p for p in procedures if p]
        if not procedures:
            continue
        lines.append(f"- {row['date']} - {', '.join(procedures)}")
        if row["findings"]:
            findings = [sanitize_for_report(f) for f in row["findings"]]
            findings = [f for f in findings if f]
            if findings:
                lines.append(f"  Findings: {', '.join(findings)}")
        cits = format_citations(row["citations"])
        if cits:
            lines.append(f"  Source: {cits}")
    return "\n".join(lines)


def render_report(events: List[ClinicalEvent], case_info: Any) -> str:
    include_timeline = False
    sections = [
        render_case_summary(events, case_info),
        render_injury_summary(events),
        render_surgical_summary(events),
    ]
    if include_timeline:
        sections.append(render_timeline(events))
    return "\n".join(sections)
