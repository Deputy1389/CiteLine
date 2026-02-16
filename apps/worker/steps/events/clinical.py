import uuid
import re
from datetime import date
from packages.shared.models import (
    Citation,
    Event,
    EventDate,
    EventType,
    Fact,
    FactKind,
    Page,
    DateKind,
    DateSource,
    Provider,
    SkippedEvent,
    Warning as PipelineWarning,
)
from apps.worker.steps.events.common import _make_citation, _make_fact, _find_section
from apps.worker.steps.step06_dates import make_partial_date

# Some PDFs split date & time across two lines:
#   "9/24"
#   "1600 Admit to Oncology Floor..."
DATE_LINE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})\s*$")
TIME_TEXT_RE = re.compile(r"^\s*(\d{3,4})\s+(.+?)\s*$")

# Sometimes it's one line: "9/24 1600 Patient ..."
DATE_TIME_TEXT_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})\s+(\d{3,4})\s+(.+?)\s*$")

_CLINICAL_INDICATORS = [
    (r"(?i)\bpain\s*(?:level|score)?\s*:?\s*(\d{1,2}/10)\b", "Pain Level"),
    (r"(?i)\b(vomiting|vomit|emesis|nausea)\b", "GI Symptom"),
    (r"(?i)\b(shortness of breath|sob|dyspnea)\b", "Respiratory Symptom"),
    (r"(?i)\b(cough|forceful coughing)\b", "Respiratory Symptom"),
    (r"(?i)\b(hospice|end of life)\b", "Care Planning"),
    (r"(?i)\b(dependent|assistance|requires help|requires partner)\b", "Functional Status"),
    (r"(?i)\b(discharge home|discharged to home)\b", "Disposition"),
]

def _detect_encounter_type(text: str) -> EventType:
    """Detect encounter type from clinical note text."""
    n = text.lower()
    
    # 1. Discharge (High Priority)
    if any(kw in n for kw in ["discharge summary", "discharged", "discharge teaching", "orders received for discharge", "discharged to home", "discharge order"]):
        return EventType.HOSPITAL_DISCHARGE
        
    # 2. Admission
    if any(kw in n for kw in ["admitted", "admission", "admit to oncology", "date admitted", "triage", "er admission", "inpatient admission", "admit to"]):
        if any(kw in n for kw in ["emergency department", "ed provider", "triage", "er visit"]):
            return EventType.ER_VISIT
        return EventType.HOSPITAL_ADMISSION
        
    # 3. Procedure
    if any(kw in n for kw in ["operative report", "procedure", "surgery"]):
        return EventType.PROCEDURE
        
    # 4. Inpatient Daily Note (Default for flowsheet context)
    # If it's not an admission/discharge/procedure, but appears in these charts, it's a daily note
    # We explicitly avoid "OFFICE_VISIT" for these types of records
    return EventType.INPATIENT_DAILY_NOTE

from apps.worker.lib.grouping import group_clinical_pages

PRIORITY_MAP = {
    EventType.ER_VISIT: 6,
    EventType.HOSPITAL_ADMISSION: 5,
    EventType.HOSPITAL_DISCHARGE: 4,
    EventType.INPATIENT_DAILY_NOTE: 3,
    EventType.PROCEDURE: 2,
    EventType.OFFICE_VISIT: 1,
}

# Some lines are just Time: "1900"
TIME_ONLY_RE = re.compile(r"^\s*(\d{3,4})\s*$")

def extract_clinical_events(
    pages: list[Page],
    dates: dict[int, list[EventDate]],
    providers: list[Provider],
    page_provider_map: dict[int, str] = {},
) -> tuple[list[Event], list[Citation], list[PipelineWarning], list[SkippedEvent]]:
    """Extract clinical note events using block grouping."""
    events: list[Event] = []
    citations: list[Citation] = []
    warnings: list[PipelineWarning] = []
    skipped: list[SkippedEvent] = []

    # 1. Group pages into blocks
    blocks = group_clinical_pages(pages, dates, providers, page_provider_map)

    for block in blocks:
        # For flowsheet docs, we'll do line-by-line scanning inside the block
        block_events, block_citations = _extract_block_events(block, page_provider_map, providers)
        
        if not block_events:
            # Fallback to the original block-level aggregation if line-scanning produced nothing
            # (e.g. for non-flowsheet structured notes)
            event_date = block.primary_date or _get_best_date(dates.get(block.pages[0].page_number, []))
            if not event_date:
                warnings.append(PipelineWarning(
                    code="MISSING_DATE",
                    message=f"Event for pages {block.page_numbers} has no resolved date",
                    page=block.pages[0].page_number
                ))
            
            block_facts: list[Fact] = []
            for page in block.pages:
                page_facts, page_cits = _extract_page_content(page)
                block_facts.extend(page_facts)
                citations.extend(page_cits)
            
            if block_facts:
                provider_id = block.primary_provider_id or (page_provider_map.get(block.pages[0].page_number) if block.pages else None) or (providers[0].provider_id if providers else "unknown")
                etype = _detect_encounter_type(" ".join(b.text for b in block_facts))
                
                events.append(Event(
                    event_id=uuid.uuid4().hex[:16],
                    provider_id=provider_id,
                    event_type=etype,
                    date=event_date,
                    facts=block_facts[:12],
                    confidence=80,
                    citation_ids=[f.citation_id for f in block_facts[:12]],
                    source_page_numbers=block.page_numbers,
                ))
            continue

        events.extend(block_events)
        citations.extend(block_citations)

    return events, citations, warnings, skipped

    return events, citations

def _is_admin_line(text: str) -> bool:
    """Check if line is a header, signature, or template label."""
    n = text.lower().strip()
    
    # 1. Exact or starts-with template labels
    prefixes = (
        "patient name:", "mrn:", "doctor name:", "dob:", 
        "chart materials", "simulation", "nurse signatures", 
        "medication administration record", "vital signs record",
        "nursing assessment flowsheet", "physician’s orders",
        "physician's orders", "page "
    )
    if n.startswith(prefixes):
        # Exception for real orders
        if "physician" in n and ("admit" in n or "discharge" in n):
            return False
        return True
        
    return False

def _is_eventworthy(text: str) -> bool:
    """Check if line contains clinical signal words."""
    n = text.lower()
    keywords = (
        "pain", "c/o", "complained", "vomit", "emesis", "nause", 
        "cough", "ambulat", "discharg", "admit", "admission",
        "orders received", "repositioned", "medicated", "ate", "denies",
        "evaluated", "seen by", "stable", "distress", "noted"
    )
    return any(k in n for k in keywords)

def _extract_block_events(block, page_provider_map, providers) -> tuple[list[Event], list[Citation]]:
    """Scan block for flowsheet rows with date context."""
    events: list[Event] = []
    citations: list[Citation] = []
    
    current_month: int | None = None
    current_day: int | None = None
    
    # Initialize from block primary date
    if block.primary_date:
         ext = block.primary_date.extensions or {}
         if ext.get("partial_month") and ext.get("partial_day"):
             current_month = int(ext["partial_month"])
             current_day = int(ext["partial_day"])
         elif block.primary_date.value:
             d = block.primary_date.value
             if isinstance(d, date):
                 current_month = d.month
                 current_day = d.day
             elif hasattr(d, "start"):
                  current_month = d.start.month
                  current_day = d.start.day

    last_event: Event | None = None
    pending_time: str | None = None
    
    for page in block.pages:
        lines = page.text.splitlines()
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # --- TASK 2: ADMIN FILTER ---
            if _is_admin_line(line):
                continue
                
            # --- TASK 1: ROW PARSING ---
            
            # Pattern A: One-line "9/24 1600 Text"
            m_full = DATE_TIME_TEXT_RE.match(line)
            if m_full:
                current_month = int(m_full.group(1))
                current_day = int(m_full.group(2))
                hhmm = m_full.group(3)
                text = m_full.group(4)
                
                if _is_eventworthy(text):
                    last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, text, page_provider_map, providers)
                else:
                    last_event = None # Reset if not worthy
                pending_time = None
                continue
                
            # Pattern B1: Date Line "9/24"
            m_date = DATE_LINE_RE.match(line)
            if m_date:
                current_month = int(m_date.group(1))
                current_day = int(m_date.group(2))
                last_event = None # New date, reset event context
                pending_time = None
                continue
                
            # Pattern B2: Standalone Time Line "1900"
            m_time_only = TIME_ONLY_RE.match(line)
            if m_time_only:
                pending_time = m_time_only.group(1)
                continue

            # Pattern B3: Time Line "1900 Text..."
            # ONLY if we have a valid date context
            if current_month and current_day:
                m_time = TIME_TEXT_RE.match(line)
                if m_time:
                    hhmm = m_time.group(1)
                    text = m_time.group(2)
                    
                    if _is_eventworthy(text):
                         last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, text, page_provider_map, providers)
                    else:
                         last_event = None
                    pending_time = None
                    continue
            
            # Pattern C: Standalone Event check (e.g. "Admit to Oncology")
            # If valid date check if it's a critical event that needs its own row
            if current_month and current_day:
                 if _is_eventworthy(line):
                      # Use pending time if available, else default to 0000
                      hhmm = pending_time or "0000"
                      last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, line, page_provider_map, providers)
                      pending_time = None
                      continue

            # Pattern D: Continuation / Untimed Clinical Text
            # If we have an active event, append text
            if last_event:
                # Append to last event as a new fact if it looks clinical
                if _is_clinical_sentence(line) or len(line) > 10: 
                    cit = _make_citation(page, line)
                    citations.append(cit)
                    last_event.facts.append(_make_fact(line, FactKind.OTHER, cit.citation_id))
                    last_event.citation_ids.append(cit.citation_id)
                    continue


    return events, citations

def _add_flowsheet_event(events, citations, page, month, day, hhmm, text, page_provider_map, providers):
    # Create the EventDate
    ed = make_partial_date(month, day)
    # Append time if we can
    ed.extensions["time"] = hhmm
    
    # Try to refine text (e.g. remove trailing initials/signatures)
    # Match: " ----T. Smyth, RN" or " --T. Smyth, RN"
    clean_txt = re.sub(r"\s*-{2,}\s*[A-Z]\.\s*[A-Za-z]+,\s*RN\s*$", "", text).strip()
    
    cit = _make_citation(page, f"{month}/{day} {hhmm} {text}")
    citations.append(cit)
    
    fact = _make_fact(clean_txt, FactKind.OTHER, cit.citation_id)
    provider_id = page_provider_map.get(page.page_number) or (providers[0].provider_id if providers else "unknown")
    
    evt = Event(
        event_id=uuid.uuid4().hex[:16],
        provider_id=provider_id,
        event_type=_detect_encounter_type(clean_txt),
        date=ed,
        facts=[fact],
        confidence=90,
        citation_ids=[cit.citation_id],
        source_page_numbers=[page.page_number],
    )
    events.append(evt)
    return evt

def _is_clinical_sentence(text: str) -> bool:
    """Return True if line contains clinical verbs/keywords."""
    n = text.lower()
    verbs = ("patient", "pt", "states", "c/o", "complained", "vomit", "medicated", "reposition", "ambulat", "discharged", "orders received", "temp", "voided")
    return any(v in n for v in verbs)

def _get_best_date(page_dates: list[EventDate]) -> EventDate | None:
    if not page_dates:
        return None
    tier1 = [d for d in page_dates if d.source == "tier1"]
    if tier1:
        return tier1[0]
    return page_dates[0]

def _is_boilerplate(text: str) -> bool:
    """Filter out common medical record legends, instructions, and non-clinical text."""
    s = " ".join(text.lower().split())
    # Strict Boilerplate Filter (Bug 2)
    lower_s = s.lower()
    
    # 1) Strong blocklist keywords
    blocklist_terms = [
        "flowsheet",
        "general appearance:", # colon important? user said general appearance
        "general appearance",
        "pressure ulcer",
        "incision",
        "rash",
        "see nursing notes",
        "see mar",
        "medication administration record",
        "national league for nursing",
        "copyright",
        "all rights reserved",
    ]
    
    has_blocklist = any(term in lower_s for term in blocklist_terms)

    if has_blocklist:
        # Check whitelist (override) - Step 3: Relaxed Filters
        whitelist_terms = [
            "patient", "admitted", "complained", "vomited", "medicated", 
            "discharged", "pain", "nausea", "coughing", "emesis", "orders received",
            "c/o", "denies", "ambulat", "reposition", "ate"
        ]
        has_whitelist = any(term in lower_s for term in whitelist_terms)
        
        if has_whitelist:
            return False # Keep it!
            
        return True

    # Header-style boilerplate (legacy)
    boilerplate_patterns = [
        r"(?i)electronically signed by",
        r"(?i)confidential medical record",
        r"(?i)page \d+ of \d+",
        r"(?i)continued on next page",
        r"_{5,}", # Long underscores (forms)
        r"[-]{5,}",
    ]
    return any(re.search(p, s) for p in boilerplate_patterns)

def _extract_page_content(page: Page) -> tuple[list[Fact], list[Citation]]:
    """Extract facts/citations from a single page using standard patterns."""
    facts: list[Fact] = []
    citations: list[Citation] = []
    
    # ── Strategy 1: Explicit Indicators (Keywords) ────────────────────
    indicator_facts, indicator_cits = _extract_indicators(page)
    facts.extend(indicator_facts)
    citations.extend(indicator_cits)

    # ── Strategy 2: Sectional extraction ──────────────────────────────
    cc = _find_section(page.text, "Chief Complaint")
    if cc:
        cit = _make_citation(page, cc)
        citations.append(cit)
        facts.append(_make_fact(cc, FactKind.CHIEF_COMPLAINT, cit.citation_id))

    # Extract HPI narrative
    for header in ["History of Present Illness", "HPI"]:
        hpi = _find_section(page.text, header)
        if hpi:
            summary = hpi[:400].strip()
            cit = _make_citation(page, summary)
            citations.append(cit)
            facts.append(_make_fact(summary, FactKind.OTHER, cit.citation_id))
            break

    # Extract assessment/diagnosis
    for header in ["Assessment", "Diagnosis", "Diagnoses", "Impression"]:
        section = _find_section(page.text, header)
        if section:
            lines = [l.strip() for l in section.split("\n") if l.strip()][:3]
            for line in lines:
                cit = _make_citation(page, line)
                citations.append(cit)
                facts.append(_make_fact(line, FactKind.ASSESSMENT, cit.citation_id))
            break

    # Extract medications (brief)
    for header in ["Medications", "Current Medications"]:
        meds = _find_section(page.text, header)
        if meds:
            lines = [l.strip() for l in meds.split("\n") if l.strip()][:3]
            for line in lines:
                cit = _make_citation(page, line)
                citations.append(cit)
                facts.append(_make_fact(line, FactKind.MEDICATION, cit.citation_id))
            break
            
    return facts, citations

def _extract_indicators(page: Page) -> tuple[list[Fact], list[Citation]]:
    """Scan for specific clinical markers that might be buried in text."""
    facts: list[Fact] = []
    citations: list[Citation] = []
    text = page.text
    
    seen_snippets = set()

    for pattern, label in _CLINICAL_INDICATORS:
        for m in re.finditer(pattern, text):
            start = max(0, m.start() - 50)
            end = min(len(text), m.end() + 100)
            snippet = text[start:end].replace("\n", " ").strip()
            
            if snippet in seen_snippets: continue
            seen_snippets.add(snippet)

            cit = _make_citation(page, snippet)
            citations.append(cit)
            facts.append(_make_fact(f"{label}: {snippet}", FactKind.OTHER, cit.citation_id))
            
    return facts, citations
