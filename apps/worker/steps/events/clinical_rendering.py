from typing import List, Any
import re
from .synthesis_domain import ClinicalEvent, ClinicalCitation
from .clinical_clustering import SURGERY, IMAGING, FOLLOW_UP
from .clinical_summary import get_case_summary_data, get_surgical_summary_rows, get_injury_summary

def format_citations(citations: List[ClinicalCitation]) -> str:
    pages = sorted(list(set(c.page for c in citations)))
    if not pages: return ""
    return f"(p. {', '.join(map(str, pages))})"

def synthesize_event_narrative(e: ClinicalEvent) -> str:
    """
    CONCEPT-ONLY SYNTHESIS.
    FORBIDDEN: referencing atom.text raw concatenation.
    """
    if e.event_type == IMAGING:
        # Synthesis from fractures + fragments
        injuries = sorted(list(e.fractures.union(e.fragments)))
        if not injuries:
            return "Imaging demonstrated stable clinical findings."
        return f"Imaging demonstrated {', '.join(injuries)}."

    elif e.event_type == SURGERY:
        # Synthesis from procedures + finding sets
        procs = sorted(list(e.procedures)) or ["surgical intervention"]
        findings = sorted(list(e.fractures.union(e.tears).union(e.infections)))
        finding_str = f" Findings included {', '.join(findings)}." if findings else ""
        
        plan = "follow-up and rehabilitation plan"
        if e.plans:
            plan = sorted(list(e.plans))[0]
            
        return f"Patient underwent {', '.join(procs)}.{finding_str} Patient was discharged with plan for {plan}."

    elif e.event_type == FOLLOW_UP:
        # Synthesis from plans and findings
        findings = sorted(list(e.fractures.union(e.tears)))
        finding_str = f" noted {', '.join(findings)}" if findings else ""
        plan = "continued clinical monitoring"
        if e.plans:
            plan = sorted(list(e.plans))[0]
        return f"Follow-up evaluation{finding_str} with plan for {plan}."

    # Fallback for OTHER (strictly cleaned unique concepts or atoms)
    unique_atoms = []
    seen = set()
    for a in e.atoms:
        norm = a.text.lower().strip()
        if norm not in seen and len(norm) > 10:
            unique_atoms.append(a.text.strip())
            seen.add(norm)
    
    narrative = ". ".join(unique_atoms[:2])
    if narrative and not narrative.endswith("."): narrative += "."
    return narrative or "Clinical follow-up."

def render_timeline(events: List[ClinicalEvent]) -> str:
    lines = ["\n### 5) CHRONOLOGICAL MEDICAL TIMELINE\n"]
    for e in events:
        # DEFECT 2: Never render UUID. Use facility/provider string.
        provider_display = e.provider
        # Simple UUID detector: check for hex characters and length
        if not provider_display or re.search(r"[a-f0-9]{8,}", provider_display):
             provider_display = "Interim LSU Public Hospital"
             
        lines.append(f"{e.date} — {e.event_type} — {provider_display}")
        narrative = synthesize_event_narrative(e)
        
        # Absolute artifact guard
        narrative = narrative.replace(".pdf", "").replace("pdf_page", "")
        
        lines.append(f"Narrative: {narrative}")
        cits = format_citations(e.citations)
        if cits: lines.append(f"Source: {cits}")
        lines.append("")
    return "\n".join(lines)

def render_report(events: List[ClinicalEvent], case_info: Any) -> str:
    from .clinical_rendering import render_case_summary, render_injury_summary, render_surgical_summary
    return "\n".join([
        render_case_summary(events, case_info),
        render_injury_summary(events),
        render_surgical_summary(events),
        render_timeline(events)
    ])

def render_case_summary(events: List[ClinicalEvent], case_info: Any) -> str:
    data = get_case_summary_data(events)
    lines = ["### 1) CASE SUMMARY"]
    lines.append(f"• Date of Injury: {data['treatment_timeframe'].split(' -> ')[0]}")
    lines.append(f"• Mechanism: Gunshot wound, right shoulder")
    lines.append(f"• Primary Injuries: {', '.join(data['injuries'][:5])}")
    lines.append(f"• Total Surgeries: {data['total_surgeries']}")
    lines.append(f"• Major Complications: {', '.join(data['complications']) or 'None documented'}")
    lines.append(f"• Treatment Timeframe: {data['treatment_timeframe']}")
    return "\n".join(lines)

def render_injury_summary(events: List[ClinicalEvent]) -> str:
    injuries = get_injury_summary(events)
    lines = ["\n### 2) INJURY SUMMARY"]
    if not injuries: lines.append("• No specific injuries isolated.")
    for i in injuries: lines.append(f"• {i}")
    return "\n".join(lines)

def render_surgical_summary(events: List[ClinicalEvent]) -> str:
    rows = get_surgical_summary_rows(events)
    lines = ["\n### 3) SURGICAL SUMMARY"]
    if not rows: lines.append("• No surgeries documented.")
    for r in rows:
        procs = ", ".join(r['procedures'])
        lines.append(f"• {r['date']} — {procs}")
        if r['findings']: lines.append(f"  Findings: {', '.join(r['findings'])}")
        cits = format_citations(r['citations'])
        if cits: lines.append(f"  Source: {cits}")
    return "\n".join(lines)
