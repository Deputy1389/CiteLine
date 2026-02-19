import uuid
import re
import os
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
DATE_LINE_RE = re.compile(r"^\s*(\d{1,2})[/\-](\d{1,2})[\.\s]*$")
TIME_LINE_RE = re.compile(r"^\s*(\d{1,2}:?\d{2})\s*(.*)$")
DATE_TIME_LINE_RE = re.compile(r"^\s*(\d{1,2})[/\-](\d{1,2})\s+(\d{1,2}:?\d{2})\s*(.*)$")
DATE_TIME_INLINE_RE = re.compile(r"(?:\b|^)(\d{1,2})[/\-](\d{1,2})\s+(\d{1,2}:?\d{2})\b")

# Author / Signer patterns
AUTHOR_RE = re.compile(r"(?i)(?:^|[\-\s]{2,})([A-Z]\.\s*[A-Za-z]+|[A-Z]{2,3}),?\s*(RN|MD|LPN|DO|NP|PA)?\s*$")

_CLINICAL_INDICATORS = [
    (r"(?i)\bpain\s*(?:level|score)?\s*:?\s*(\d{1,2}/10)\b", "Pain Level"),
    (r"(?i)diagnosis\s*:\s*([^.\n]+)", "Diagnosis"),
    (r"(?i)\b(adenocarcinoma|carcinoma|cancer|malignancy)\b", "Diagnosis"),
    (r"(?i)\b(vomiting|vomit|emesis|nausea)\b", "GI Symptom"),
    (r"(?i)\b(shortness of breath|sob|dyspnea)\b", "Respiratory Symptom"),
    (r"(?i)\b(cough|forceful coughing)\b", "Respiratory Symptom"),
    (r"(?i)\b(hospice|end of life)\b", "Care Planning"),
    (r"(?i)\b(dependent|assistance|requires help|requires partner)\b", "Functional Status"),
    (r"(?i)\b(discharge home|discharged to home)\b", "Disposition"),
    (r"(?i)\bwt\s*:\s*(\d{2,3})\b", "Weight"),
    (r"(?i)history\s*of\s*([^.\n]+)", "Medical History"),
]

def _append_to_event(event: Event, text: str, page: Page, citations: list[Citation], author_name=None, author_role=None):
    """Append a clinical line to an existing event fact list."""
    cit = _make_citation(page, text)
    citations.append(cit)
    
    # Update encounter type if new text is stronger
    new_etype = _detect_encounter_type(text)
    if PRIORITY_MAP.get(new_etype, 0) > PRIORITY_MAP.get(event.event_type, 0):
        event.event_type = new_etype

    # Update author if provided and currently unknown or if new author has higher rank? 
    # For now, just set if missing.
    if author_name and not event.author_name:
        event.author_name = author_name
        event.author_role = author_role

    # Check if this line contains new indicators
    fact_text = text
    for pattern, label in _CLINICAL_INDICATORS:
        if re.search(pattern, text):
            if label not in text:
                fact_text = f"{label}: {text}"
            break

    event.facts.append(_make_fact(fact_text, FactKind.OTHER, cit.citation_id))
    event.citation_ids.append(cit.citation_id)

def _detect_encounter_type(text: str) -> EventType:
    """Detect encounter type from clinical note text with deterministic rules."""
    n = text.lower()
    
    # 0. Historical Reference Detection
    # If text contains "on MM/DD" or "prior to" but it's not a header/row, it's a reference
    # "discharged home on 9/22", "history of adenocarcinoma of the lung"
    if re.search(r"\b(discharged home on|admitted on|prior to|reported on|history of)\s+\d{1,2}/\d{1,2}\b", n):
        return EventType.REFERENCED_PRIOR_EVENT
    
    # History of ... (without date) is often just a daily note mention
    if "history of" in n and len(n) < 100:
        return EventType.REFERENCED_PRIOR_EVENT

    # 1. Discharge
    if any(kw in n for kw in ["discharge summary", "discharged", "discharge teaching", "orders received for discharge", "discharged to home", "discharge order", "patient discharged"]):
        return EventType.HOSPITAL_DISCHARGE

    # 1.5 Explicit ED/ER visit cues that may not include admission wording.
    if re.search(r"\b(seen in er|seen in ed|er visit|ed visit|emergency room|emergency department)\b", n):
        return EventType.ER_VISIT
        
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
                    # Prefer any candidate that HAS a full date value if available
                    full_dates = [d for d in candidates if d.value is not None]
                    if full_dates:
                        event_date = full_dates[0]
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

    # 3. Global assessment extraction
    assessment_findings = _extract_assessment_findings(pages)
    if events and assessment_findings:
        if not events[0].extensions: events[0].extensions = {}
        events[0].extensions["assessment_findings"] = assessment_findings

    return events, citations, warnings, skipped

def _is_boilerplate_line(text: str) -> bool:
    """Hard drop deterministic boilerplate/admin lines."""
    # Normalize whitespace for matching
    n = " ".join(text.lower().split())
    
    # STEP 2 INVARIANT: NEVER drop a line that contains a clinical timestamp pattern
    # A) MM/DD HHMM anywhere
    if re.search(r"\b\d{1,2}[/\-]\d{1,2}\s+\d{1,2}:?\d{2}\b", text):
        return False
    # B) HHMM at start (likely clinical note row)
    if re.search(r"^\s*\d{1,2}:?\d{2}\b", text):
        return False
        
    # NEW: Never drop if it contains high-value keywords
    if any(kw in n for kw in ["pain", "vomit", "oxycodone", "cough", "fall risk"]):
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
        r"patient chart",
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
        r"^date\s*:\s*$",
        r"^medication\s*:\s*$",
        r"^vital signs record\s*$",
        r"^date of order\s*$",
        r"^date/time given\s*$",
        r"^weight\s*$",
        r"^respirations\s*$",
        r"^temp\s*$",
    ]
    
    if any(re.search(p, n) for p in boilerplate_patterns):
        return True
        
    # 4. Template noise
    prefixes = (
        "page ", "physician’s orders", "physician's orders", "dates", "time hourly",
        "pain assessment", "intensity (", "date:", "medication:", "date of order",
        "date/time given"
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
        "evaluated", "seen by", "stable", "distress", "noted",
        "oxycodone", "phenergan", "ibuprofen", "dentures", "sores",
        "edema", "kyphosis", "weight", "wt:", "fall risk", "assistance",
        "summary", "teaching", "bath", "urinated"
    )
    return any(k in n for k in keywords)

def _is_same_timestamp(event: Event, month: int, day: int, hhmm: str | None) -> bool:
    """True if the event matches the given month, day, and time."""
    if not event.date: return False
    ext = event.date.extensions or {}
    return (
        event.date.partial_month == month and
        event.date.partial_day == day and
        ext.get("time") == hhmm
    )

def _extract_block_events(block, page_provider_map, providers) -> tuple[list[Event], list[Citation]]:
    """Scan block for flowsheet rows with date context and rowization."""
    events: list[Event] = []
    citations: list[Citation] = []
    
    debug_enabled = os.environ.get("CLINICAL_DEBUG") == "1"

    # Block-level default context
    block_month: int | None = None
    block_day: int | None = None
    block_year: int | None = None
    
    if block.primary_date:
         ext = block.primary_date.extensions or {}
         if ext.get("partial_month") and ext.get("partial_day"):
             block_month = int(ext["partial_month"])
             block_day = int(ext["partial_day"])
             # If it was partial, it might NOT have a value.year
         
         if block.primary_date.value and isinstance(block.primary_date.value, date):
             d = block.primary_date.value
             block_month = d.month
             block_day = d.day
             block_year = d.year
         elif block.primary_date.value and hasattr(block.primary_date.value, "start"):
              block_month = block.primary_date.value.start.month
              block_day = block.primary_date.value.start.day
              block_year = block.primary_date.value.start.year

    for page in block.pages:
        # Per-page context starts with block context
        current_month = block_month
        current_day = block_day
        current_year = block_year
        current_author = None
        current_role = None
        
        last_event: Event | None = None
        pending_time: str | None = None
        
        lines = page.text.splitlines()
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # 1. Deterministic Boilerplate Filter
            if _is_boilerplate_line(line):
                continue

            # 2. Author / Signature Detection (Check for author on every line)
            m_author = AUTHOR_RE.search(line)
            if m_author:
                current_author = m_author.group(1).strip()
                current_role = m_author.group(2).strip() if m_author.group(2) else None

            # 3. Date/Time Detection
            m_dt = DATE_TIME_LINE_RE.match(line)
            m_inline = DATE_TIME_INLINE_RE.search(line)
            m_date = DATE_LINE_RE.match(line)
            m_time = TIME_LINE_RE.match(line)

            if m_dt:
                m, d = int(m_dt.group(1)), int(m_dt.group(2))
                hhmm = m_dt.group(3).replace(":", "")
                text = m_dt.group(4).strip()
                current_month, current_day, current_year = m, d, None
                
                if text:
                    if last_event and _is_same_timestamp(last_event, m, d, hhmm):
                        _append_to_event(last_event, text, page, citations, author_name=current_author, author_role=current_role)
                    else:
                        last_event = _add_flowsheet_event(events, citations, page, m, d, hhmm, text, page_provider_map, providers, debug_enabled, year=current_year, author_name=current_author, author_role=current_role)
                    pending_time = None
                else:
                    # New timestamp context
                    last_event = None
                    pending_time = hhmm
                continue

            elif m_inline:
                m, d = int(m_inline.group(1)), int(m_inline.group(2))
                hhmm = m_inline.group(3).replace(":", "")
                current_month, current_day, current_year = m, d, None
                
                text_start = m_inline.end()
                text = line[text_start:].strip()
                if text:
                    if last_event and _is_same_timestamp(last_event, m, d, hhmm):
                        _append_to_event(last_event, text, page, citations, author_name=current_author, author_role=current_role)
                    else:
                        last_event = _add_flowsheet_event(events, citations, page, m, d, hhmm, text, page_provider_map, providers, debug_enabled, year=current_year, author_name=current_author, author_role=current_role)
                    pending_time = None
                else:
                    # Context switch
                    last_event = None
                    pending_time = hhmm
                continue

            elif m_date:
                current_month = int(m_date.group(1))
                current_day = int(m_date.group(2))
                current_year = None
                last_event = None
                pending_time = None
                continue

            elif m_time:
                hhmm = m_time.group(1).replace(":", "")
                text = m_time.group(2).strip()
                
                if current_month and current_day:
                    if text and _is_eventworthy(text):
                        if last_event and _is_same_timestamp(last_event, current_month, current_day, hhmm):
                            _append_to_event(last_event, text, page, citations, author_name=current_author, author_role=current_role)
                        else:
                            last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, text, page_provider_map, providers, debug_enabled, year=current_year, author_name=current_author, author_role=current_role)
                    else:
                        last_event = None
                        pending_time = hhmm
                else:
                    pending_time = hhmm
                continue

            # 4. Continuation or Standalone Clinical Text
            if current_month and current_day:
                if _is_eventworthy(line):
                    hhmm = pending_time or None
                    if last_event and _is_same_timestamp(last_event, current_month, current_day, hhmm):
                        _append_to_event(last_event, line, page, citations, author_name=current_author, author_role=current_role)
                    else:
                        last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, line, page_provider_map, providers, debug_enabled, year=current_year, author_name=current_author, author_role=current_role)
                    pending_time = None
                elif last_event and (_is_clinical_sentence(line) or len(line) > 10):
                    _append_to_event(last_event, line, page, citations, author_name=current_author, author_role=current_role)
                elif not last_event and _is_clinical_sentence(line):
                    hhmm = pending_time or None
                    last_event = _add_flowsheet_event(events, citations, page, current_month, current_day, hhmm, line, page_provider_map, providers, debug_enabled, year=current_year, author_name=current_author, author_role=current_role)
                    pending_time = None

    return events, citations

def _add_flowsheet_event(events, citations, page, month, day, hhmm, text, page_provider_map, providers, debug_enabled=False, year=None, author_name=None, author_role=None):
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
    
    if year:
        try:
            ed.value = date(year, month, day)
            ed.extensions["year_missing"] = False
            ed.source = DateSource.TIER1
        except ValueError:
            pass

    # Try to refine text (e.g. remove trailing initials/signatures)
    clean_txt = re.sub(r"\s*-{2,}\s*[A-Z]\.\s*[A-Za-z]+,\s*RN\s*$", "", clean_txt).strip()
    clean_txt = re.sub(r"\s*[A-Z]\.\s*[A-Za-z]+,\s*RN\s*$", "", clean_txt).strip()

    if not clean_txt:
        return None

    etype = _detect_encounter_type(clean_txt)
    confidence = 90
    event_flags = []
    
    if etype == EventType.REFERENCED_PRIOR_EVENT:
        confidence = 50
        event_flags.append("is_reference")

    cit = _make_citation(page, f"{month}/{day} {hhmm} {text}")
    citations.append(cit)
    
    fact = _make_fact(clean_txt, FactKind.OTHER, cit.citation_id)
    
    # NEW: Check for specific indicators in this line to upgrade fact kind or text
    for pattern, label in _CLINICAL_INDICATORS:
        if re.search(pattern, clean_txt):
            # Prepend label if not already present
            if label not in clean_txt:
                fact.text = f"{label}: {clean_txt}"
            break

    provider_id = page_provider_map.get(page.page_number) or (providers[0].provider_id if providers else "unknown")
    
    evt = Event(
        event_id=uuid.uuid4().hex[:16],
        provider_id=provider_id,
        event_type=etype,
        date=ed,
        encounter_type_raw=etype.value,
        author_name=author_name,
        author_role=author_role,
        facts=[fact],
        confidence=confidence,
        flags=event_flags,
        citation_ids=[cit.citation_id],
        source_page_numbers=[page.page_number],
    )
    
    if debug_enabled:
        date_str = f"{month:02d}/{day:02d}"
        print(f"CLINICAL_DEBUG: Emitting event: doc={page.source_document_id}, page={page.page_number}, type={etype.value}, date={date_str}, text={clean_txt[:80]}...")
    
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

def _extract_assessment_findings(pages: list[Page]) -> dict[str, str]:
    """Scan all pages for specific high-value assessment findings."""
    findings = {}
    text = "\n".join(p.text for p in pages)
    
    # 1. Fall Risk
    m = re.search(r"(?i)fall\s*risk\s*score\s*:?\s*(\d+)", text)
    if m: findings["fall_risk"] = m.group(1)
    
    # 2. Edema
    m = re.search(r"(?i)(\d\+?\s*(?:bilateral)?\s*lower\s*extremity\s*pitting\s*edema)", text)
    if m: findings["edema"] = m.group(1)
    
    # 3. Kyphosis
    if re.search(r"(?i)kyphosis", text): findings["kyphosis"] = "Noted"
    
    # 4. Weight Loss
    weights = re.findall(r"(?i)wt\s*:\s*(\d{2,3})", text)
    if len(weights) >= 2:
        unique_weights = []
        for w in weights:
            if w not in unique_weights: unique_weights.append(w)
        if len(unique_weights) >= 2:
            findings["weight_history"] = " -> ".join(unique_weights) + " lbs"
        
    return findings
