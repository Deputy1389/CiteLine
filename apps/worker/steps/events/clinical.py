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

# Flexible pattern: detect date and time anywhere in the line
# e.g. "9/26 0925 Text" or "T. Smyth, RN 9/26 0925 Text"
DATE_TIME_INLINE_RE = re.compile(r"(?:\b|^)(\d{1,2})/(\d{1,2})\s+(\d{3,4})\b")

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
    """Detect encounter type from clinical note text with deterministic rules."""
    n = text.lower()
    
    # 1. Discharge
    if any(kw in n for kw in ["discharge summary", "discharged", "discharge teaching", "orders received for discharge", "discharged to home", "discharge order", "patient discharged"]):
        return EventType.HOSPITAL_DISCHARGE
        
    # 2. Admission (Avoid labels like "Date Admitted:")
    if re.search(r"\b(admitted|admission|admit to oncology|triage|er admission|inpatient admission|admit to oncology floor)\b", n):
        if not re.search(r"date\s+admitted\s*:", n): # Skip labels
            if any(kw in n for kw in ["emergency department", "ed provider", "triage", "er visit"]):
                return EventType.ER_VISIT
            return EventType.HOSPITAL_ADMISSION
        
    # 3. Procedure
    if any(kw in n for kw in ["operative report", "procedure", "surgery"]):
        return EventType.PROCEDURE
        
    # Default for inpatient records
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
            # Fallback to the original block-level aggregation if line-scanning produced nothing.
            # IMPORTANT: do NOT anchor the entire block to the first page's date.
            # Many blocks contain multiple days (e.g. admission page + later discharge page).

            block_facts: list[Fact] = []
            for page in block.pages:
                page_facts, page_cits = _extract_page_content(page)
                block_facts.extend(page_facts)
                citations.extend(page_cits)

            if not block_facts:
                skipped.append(SkippedEvent(
                    page_numbers=block.page_numbers,
                    reason_code="NO_FACTS",
                    snippet=block.pages[0].text[:200] if block.pages else "No text",
                ))
                continue

            provider_id = (
                block.primary_provider_id
                or (page_provider_map.get(block.pages[0].page_number) if block.pages else None)
                or (providers[0].provider_id if providers else "unknown")
            )
            etype = _detect_encounter_type(" ".join(f.text for f in block_facts))

            # Collect candidate dates across ALL pages in the block.
            # Prefer a max date for discharge-like events, otherwise prefer the earliest.
            candidates: list[EventDate] = []
            for p in block.pages:
                candidates.extend(dates.get(p.page_number, []) or [])

            event_date: EventDate | None = None
            event_flags: list[str] = []
            if candidates:
                if etype == EventType.HOSPITAL_DISCHARGE:
                    event_date = max(candidates, key=lambda d: d.sort_key())
                elif etype == EventType.HOSPITAL_ADMISSION:
                    event_date = min(candidates, key=lambda d: d.sort_key())
                else:
                    event_date = block.primary_date or min(candidates, key=lambda d: d.sort_key())
            else:
                event_date = block.primary_date

            if not event_date:
                warnings.append(PipelineWarning(
                    code="MISSING_DATE",
                    message=f"Event for pages {block.page_numbers} has no resolved date",
                    page=block.pages[0].page_number,
                ))
                event_flags.append("MISSING_DATE")

            events.append(Event(
                event_id=uuid.uuid4().hex[:16],
                provider_id=provider_id,
                event_type=etype,
                date=event_date,
                facts=block_facts[:12],
                confidence=80,
                flags=event_flags,
                citation_ids=[f.citation_id for f in block_facts[:12]],
                source_page_numbers=block.page_numbers,
            ))
            continue

        events.extend(block_events)
        citations.extend(block_citations)

    return events, citations, warnings, skipped

def _is_boilerplate_line(text: str) -> bool:
    """Hard drop deterministic boilerplate/admin lines."""
    # Normalize whitespace for matching
    n = " ".join(text.lower().split())
    
    # STEP 2 INVARIANT: NEVER drop a line that contains a clinical timestamp pattern
    # A) MM/DD HHMM anywhere
    if re.search(r"\b\d{1,2}/\d{1,2}\s+\d{3,4}\b", text):
        return False
    # B) HHMM at start (likely clinical note row)
    if re.search(r"^\s*\d{3,4}\b", text):
        return False

    # 1. Staff Signatures / Names (e.g. "Teri Smyth, RN", "Maria Reyes, RN")
    if re.search(r",\s*rn\b", n):
        # If the line is JUST the name or mostly just name/dashes
        # " ----T. Smyth, RN"
        if len(re.sub(r"[^a-z]", "", n)) < 25: 
             return True
             
    # 2. Separators and Lines
    if re.match(r"^[_\-\s\*=]{3,}$", n):
        return True
        
    # 3. Bug 2: Hard drop patterns (Flexible whitespace)
    boilerplate_patterns = [
        r"national league for nursing",
        r"chart materials",
        r"simulation",
        r"patient name\s*:",
        r"mrn\s*:",
        r"doctor name\s*:",
        r"dob\s*:",
        r"nurse signatures?",
        r"scheduled & routine drugs",
        r"allergies\s*:",
        r"medication administration record",
        r"intramuscular legend",
        r"subcutaneous site code",
        r"fluid measurements",
        r"sample measurements",
        r"time: site: initials",
        r"see nurs[ei]s? notes",
        r"see mar",
        r"pain type\s*:",
        r"pain interventions?\s*:",
        r"positioning\s*:",
        r"pt\. hygiene\s*:",
        r"wound assessment",
        r"wound drainage",
        r"wound care\s*:",
        r"braden scale",
        r"fall risk score",
        r"today’s wt\s*:",
        r"yesterday’s wt\s*:",
        r"hourly",
        r"iv solution",
        r"rate ordered\s*:",
        r"date/time hung\s*:",
        r"intensity \(1-10/10\)",
        r"mucous membranes\s*:",
        r"iv site/rate",
        r"patient hygiene",
        r"po fluids",
        r"nurse initials",
        r"legend\s*\)",
        r"[a-z]=\s*[a-z]{4} ventrogluteal", # Legend codes
        r"\d=[a-z]{3} abdomen",
        r"hours to be given",
    ]
    
    if any(re.search(p, n) for p in boilerplate_patterns):
        return True
        
    # 4. Template noise
    prefixes = (
        "page ", "vital signs record", "nursing assessment flowsheet", 
        "physician’s orders", "physician's orders", "dates", "time hourly",
        "pain assessment", "intensity ("
    )
    if n.startswith(prefixes):
        # Exception for real orders
        if "admit" in n or "discharge" in n:
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
    """Scan block for flowsheet rows with date context and rowization."""
    events: list[Event] = []
    citations: list[Citation] = []
    
    # Block-level default context
    block_month: int | None = None
    block_day: int | None = None
    
    if block.primary_date:
         ext = block.primary_date.extensions or {}
         if ext.get("partial_month") and ext.get("partial_day"):
             block_month = int(ext["partial_month"])
             block_day = int(ext["partial_day"])
         elif block.primary_date.value:
             d = block.primary_date.value
             if isinstance(d, date):
                 block_month = d.month
                 block_day = d.day
             elif hasattr(d, "start"):
                  block_month = d.start.month
                  block_day = d.start.day

    for page in block.pages:
        # Per-page context starts with block context
        current_month = block_month
        current_day = block_day
        
        last_event: Event | None = None
        pending_time: str | None = None
        
        lines = page.text.splitlines()
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # STEP 3: Detect date anywhere in line
            # e.g. "T. Smyth, RN 9/26 0430 Patient ..."
            m_inline = DATE_TIME_INLINE_RE.search(line)
            if m_inline:
                current_month = int(m_inline.group(1))
                current_day = int(m_inline.group(2))
                # If we have a time too, and text remains
                hhmm = m_inline.group(3)
                # Remaining text after the timestamp
                text_start = m_inline.end()
                text = line[text_start:].strip()
                
                if text and _is_eventworthy(text):
                    last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, text, page_provider_map, providers)
                    pending_time = None
                    continue
                else:
                    # Just update context
                    pending_time = hhmm
                    # If we don't have text yet, it might be on the next line
                    # continue to let subsequent patterns handle it or next line

            # 1. Deterministic Boilerplate Filter
            if _is_boilerplate_line(line):
                continue
                
            # 2. Date Line Pattern: ^\d{1,2}/\d{1,2}$
            m_date = DATE_LINE_RE.match(line)
            if m_date:
                current_month = int(m_date.group(1))
                current_day = int(m_date.group(2))
                last_event = None 
                pending_time = None
                continue
                
            # 3. One-line Pattern: ^\d{1,2}/\d{1,2}\s+\d{3,4}\s+<text>
            m_full = DATE_TIME_TEXT_RE.match(line)
            if m_full:
                current_month = int(m_full.group(1))
                current_day = int(m_full.group(2))
                hhmm = m_full.group(3)
                text = m_full.group(4)
                
                if _is_eventworthy(text):
                    last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, text, page_provider_map, providers)
                else:
                    last_event = None
                pending_time = None
                continue

            # 4. Time Line Pattern: ^\d{3,4}\s+<text>
            m_time_text = TIME_TEXT_RE.match(line)
            if m_time_text:
                hhmm = m_time_text.group(1)
                text = m_time_text.group(2)
                
                if current_month and current_day:
                    if _is_eventworthy(text):
                        last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, text, page_provider_map, providers)
                    else:
                        last_event = None
                else:
                    # Mark undated / skip from calculations as per Rule 4
                    last_event = None
                pending_time = None
                continue

            # 5. Standalone Time Pattern: ^\d{3,4}$
            m_time_only = TIME_ONLY_RE.match(line)
            if m_time_only:
                pending_time = m_time_only.group(1)
                continue

            # 6. Continuation or Standalone Clinical Text
            if current_month and current_day:
                if _is_eventworthy(line) or (last_event and (_is_clinical_sentence(line) or len(line) > 10)):
                    if last_event and not _is_eventworthy(line):
                        # Append to last event
                        cit = _make_citation(page, line)
                        citations.append(cit)
                        last_event.facts.append(_make_fact(line, FactKind.OTHER, cit.citation_id))
                        last_event.citation_ids.append(cit.citation_id)
                    else:
                        # New event with pending or default time
                        hhmm = pending_time or "0000"
                        last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, line, page_provider_map, providers)
                        pending_time = None
                continue

    return events, citations

def _add_flowsheet_event(events, citations, page, month, day, hhmm, text, page_provider_map, providers):
    if not month or not day:
        return None

    # Task 4: Staff Filter before creation
    clean_txt = text.strip()
    
    # Drop separators
    if re.match(r"^[_\-\s\*=]{3,}$", clean_txt):
        return None
        
    # Drop name-only lines
    if re.search(r",\s*rn\s*$", clean_txt.lower()):
         if len(clean_txt) < 30: # Likely just name
              return None

    # Create the EventDate
    ed = make_partial_date(month, day)
    # Append time if we can
    ed.extensions["time"] = hhmm
    
    # Try to refine text (e.g. remove trailing initials/signatures)
    clean_txt = re.sub(r"\s*-{2,}\s*[A-Z]\.\s*[A-Za-z]+,\s*RN\s*$", "", clean_txt).strip()
    clean_txt = re.sub(r"\s*[A-Z]\.\s*[A-Za-z]+,\s*RN\s*$", "", clean_txt).strip()

    if not clean_txt:
        return None

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
    
    # DEBUG Print Task 1
    # print(f"EMITTING: [{month:02d}/{day:02d} {hhmm}] {evt.event_type.value}: {clean_txt[:60]}... (Source: {page.source_document_id} p.{page.page_number})")
    
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
