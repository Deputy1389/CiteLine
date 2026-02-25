from typing import List
from datetime import date as date_type
from .synthesis_domain import ClinicalAtom, ClinicalEvent
from .clinical_filtering import is_noise_line, normalize_text

# Event Types
SURGERY = "SURGERY"
IMAGING = "IMAGING"
WOUND_CARE = "WOUND_CARE"
THERAPY_REHAB = "THERAPY_REHAB"
FOLLOW_UP = "FOLLOW_UP"
PREOPERATIVE_NOTE = "PREOPERATIVE_NOTE"
OTHER = "OTHER"

def classify_event(atoms: List[ClinicalAtom]) -> str:
    text_blob = " ".join([a.text.lower() for a in atoms])
    
    # Priority 1: SURGERY (Strict Guard)
    surgery_anchors = [
        "operative report", "procedure performed", "incision", 
        "anesthesia", "repair performed", "pacu", "operating room"
    ]
    has_surgery_anchor = any(anchor in text_blob for anchor in surgery_anchors)
    
    # Priority 2: IMAGING
    imaging_anchors = ["x-ray", "xr", "ct", "cta", "mri", "impression", "radiology"]
    has_imaging_anchor = any(anchor in text_blob for anchor in imaging_anchors)

    # Priority 2b: THERAPY
    therapy_anchors = ["physical therapy", "rom", "range of motion", "therapeutic exercise", "pt session"]
    has_therapy_anchor = any(anchor in text_blob for anchor in therapy_anchors)

    if has_surgery_anchor:
        # Guard: do not classify follow-up/status-post narratives as surgery unless
        # there is active OR/procedure context.
        followup_anchors = ["follow up", "clinic", "evaluation", "status post", "s/p", "post op", "suture removal"]
        strong_or_anchors = [
            "operative report",
            "procedure performed",
            "anesthesia",
            "operating room",
            "incision",
            "closure",
            "pacu",
            "postop diagnosis",
            "preop diagnosis",
        ]
        has_followup_context = any(anchor in text_blob for anchor in followup_anchors)
        has_strong_or_context = any(anchor in text_blob for anchor in strong_or_anchors)
        if has_followup_context and not has_strong_or_context:
            return FOLLOW_UP
        # Safety: downgrade to IMAGING if text is primarily imaging phrasing
        imaging_phrases = ["appeared located", "visualized", "no evidence of"]
        if any(p in text_blob for p in imaging_phrases) and not "incision" in text_blob:
             return IMAGING
        return SURGERY
        
    if has_imaging_anchor:
        return IMAGING

    if has_therapy_anchor:
        return THERAPY_REHAB

    # Priority 3: PREOPERATIVE_NOTE
    preop_anchors = ["pre-operative", "preoperative", "catheter", "consented", "anesthesia consultation"]
    if any(anchor in text_blob for anchor in preop_anchors):
        return PREOPERATIVE_NOTE
        
    # Priority 4: FOLLOW_UP
    followup_anchors = ["follow up", "clinic", "evaluation", "post op", "suture removal"]
    if any(anchor in text_blob for anchor in followup_anchors):
        return FOLLOW_UP
        
    return OTHER

def cluster_atoms_into_events(atoms: List[ClinicalAtom]) -> List[ClinicalEvent]:
    from collections import defaultdict
    # STEP 1: Strict atom-level noise filter before any processing
    cleaned = [a for a in atoms if not is_noise_line(a.text)]
    
    by_date = defaultdict(list)
    for a in cleaned:
        if a.date and isinstance(a.date, date_type) and a.date.year >= 1970:
            by_date[a.date].append(a)
        
    events = []
    
    # Track therapy sessions for compression
    therapy_sessions_by_facility = defaultdict(list)

    for day in sorted(by_date.keys()):
        day_atoms = by_date[day]
        etype = classify_event(day_atoms)
        
        # Resolve provider
        providers = [a.provider for a in day_atoms if a.provider]
        provider = max(set(providers), key=providers.count) if providers else "Unknown Provider"
        facility = day_atoms[0].facility if day_atoms[0].facility else provider

        if etype == THERAPY_REHAB:
            therapy_sessions_by_facility[facility].append((day, day_atoms))
            continue # Defer therapy events for compression

        # Merge citations
        all_cits = []
        seen = set()
        for a in day_atoms:
            for c in a.citations:
                if (c.doc_id, c.page) not in seen:
                    all_cits.append(c)
                    seen.add((c.doc_id, c.page))
                    
        events.append(ClinicalEvent(
            date=day,
            event_type=etype,
            title=etype.replace("_", " ").title(),
            atoms=day_atoms, # Strictly uses filtered atoms
            citations=all_cits,
            provider=provider,
            facility=facility
        ))

    # STEP 2: Therapy Compression
    # If >5 similar PT entries in 30-day window, summarize them.
    for facility, sessions in therapy_sessions_by_facility.items():
        if not sessions: continue
        
        sessions.sort(key=lambda x: x[0])
        
        # Group sessions into 30-day windows
        current_batch = []
        batch_start_date = None
        
        for day, day_atoms in sessions:
            if not batch_start_date or (day - batch_start_date).days > 30:
                if current_batch:
                    events.append(_create_therapy_summary(current_batch, facility))
                current_batch = [(day, day_atoms)]
                batch_start_date = day
            else:
                current_batch.append((day, day_atoms))
        
        if current_batch:
            events.append(_create_therapy_summary(current_batch, facility))

    return sorted(events, key=lambda e: e.date)

def _create_therapy_summary(batch: List[tuple], facility: str) -> ClinicalEvent:
    """Creates a summarized block for a course of therapy, now with litigation-grade phasing."""
    start_date = batch[0][0]
    end_date = batch[-1][0]
    all_atoms = []
    all_cits = []
    seen_cits = set()
    
    for _, atoms in batch:
        all_atoms.extend(atoms)
        for a in atoms:
            for c in a.citations:
                if (c.doc_id, c.page) not in seen_cits:
                    all_cits.append(c)
                    seen_cits.add((c.doc_id, c.page))
    
    visit_count = len(batch)
    
    # DETERMINE PHASE (Litigation Advocacy Logic)
    # Acute: first 30 days of treatment
    # Subacute: 31-90 days
    # Recovery: >90 days
    # (Note: batch is already within a 30-day window from caller, but we check absolute duration from first visit if we had it)
    # Since we only have the batch here, we'll label based on the visit count and relative density
    phase_label = "Acute Phase"
    if visit_count < 3: phase_label = "Maintenance/Recovery Phase"
    elif 3 <= visit_count <= 8: phase_label = "Subacute Phase"
    
    summary_text = f"[{phase_label}] {visit_count} sessions documented at {facility}."
    
    # Try to extract trend
    pain_scores = []
    import re
    for a in all_atoms:
        m = re.search(r"pain\s*(?:level|score)?\s*[:=]?\s*(\d+)/10", a.text.lower())
        if m: pain_scores.append(int(m.group(1)))
    
    if pain_scores:
        start_pain = pain_scores[0]
        end_pain = pain_scores[-1]
        if start_pain > end_pain:
            summary_text += f" Documenting significant improvement in pain from {start_pain}/10 to {end_pain}/10."
        elif start_pain < end_pain:
            summary_text += f" Noted persistent/increased pain levels peaking at {max(pain_scores)}/10."
        else:
            summary_text += f" Documenting persistent high-intensity pain at {start_pain}/10."

    # Add Objective Findings Summary to the therapy block
    findings = set()
    for a in all_atoms:
        t = a.text.lower()
        if "spasm" in t: findings.add("spasm")
        if "guarding" in t: findings.add("guarding")
        if "limited" in t and "rom" in t: findings.add("ROM restrictions")
    
    if findings:
        summary_text += f" Clinical observations: {', '.join(sorted(list(findings)))}."

    summary_atom = ClinicalAtom(
        date=start_date,
        text=summary_text,
        kind="encounter",
        citations=all_cits,
        facility=facility
    )

    return ClinicalEvent(
        date=start_date,
        event_type=THERAPY_REHAB,
        title=f"Therapy: {phase_label}",
        atoms=[summary_atom],
        citations=all_cits,
        provider=facility,
        facility=facility
    )
