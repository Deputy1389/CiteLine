import re
from datetime import date
from apps.worker.project.models import ChronologyProjectionEntry
from apps.worker.steps.events.report_quality import date_sanity, procedure_canonicalization, injury_canonicalization
from packages.shared.utils.noise_utils import is_vitals_heavy, is_flowsheet_noise
from packages.shared.models import Event

MIN_SUBSTANCE_THRESHOLD = 1

_ED_MARKER_RE = re.compile(
    r"\b("
    r"ed notes?|emergency department|emergency room|er visit|triage|chief complaint|"
    r"history of present illness|hpi|trauma center"
    r")\b",
    re.IGNORECASE,
)

_MECHANISM_MARKER_RE = re.compile(
    r"\b("
    r"rear[- ]end|motor vehicle collision|mvc|mva|auto accident|car accident|collision|head-on|T-bone|side-impact"
    r")\b",
    re.IGNORECASE,
)


def is_ed_event(
    *,
    text_blob: str,
    event_type: str = "",
    provider_blob: str = "",
    event_class: str = "",
) -> bool:
    low_text = (text_blob or "").lower()
    low_event_type = (event_type or "").lower()
    low_provider = (provider_blob or "").lower()
    low_event_class = (event_class or "").lower()
    if low_event_class == "ed_visit":
        return True
    if _ED_MARKER_RE.search(low_text):
        return True
    if re.search(r"\b(emergency department|emergency room|er visit|ed visit|trauma center)\b", low_text):
        return True
    if re.search(r"\b(emergency|er visit)\b", low_event_type):
        return True
    if re.search(r"\b(emergency|trauma)\b", low_provider):
        return True
    return False


def _mechanism_priority_score(text: str) -> int:
    low = text.lower()
    score = 0
    if _MECHANISM_MARKER_RE.search(low):
        score += 15
    if re.search(r"\bpain(?:\s*(?:score|severity|level))?\s*[:=]?\s*\d{1,2}\s*/\s*10\b", low):
        score += 5
    if re.search(r"\b(denies?|no prior|without prior|prior complaints?)\b", low):
        score += 5
    return score

def is_high_value_event(event: Event, joined_raw: str) -> bool:
    ext = event.extensions or {}
    sev = ext.get("severity_score")
    if isinstance(sev, int) and sev >= 55:
        return True

    low = joined_raw.lower()
    concept_hit = bool(procedure_canonicalization(joined_raw) or injury_canonicalization(joined_raw))
    if concept_hit:
        return True

    high_priority_types = {
        "er_visit", "hospital_admission", "hospital_discharge", "discharge", "procedure", "imaging_study", "inpatient_daily_note", "lab_result",
    }
    if event.event_type.value in high_priority_types:
        if event.event_type.value == "imaging_study":
            return bool(re.search(r"\b(impression|x-?ray|ct|mri|ultrasound|angiogram|fracture|tear|lesion)\b", low))
        return True

    severe_signal = bool(re.search(r"\b(phq-?9|depression|suicid|homeless|skilled nursing|emergency room|er visit|admission|discharge|opioid|hydrocodone|oxycodone|codeine)\b", low))
    if severe_signal:
        return True

    if is_vitals_heavy(joined_raw):
        return False

    meaningful_clinic_signal = bool(re.search(r"\b(diagnosis|assessment|impression|fracture|infection|tear|follow-?up|medication|prescribed|therapy|plan|disposition|discharge)\b", low))
    questionnaire_only = bool(re.search(r"\b(phq-?9|gad-?7|pain interference|questionnaire|survey score|score)\b", low)) and not bool(re.search(r"\b(admission|discharge|diagnosis|impression|procedure|surgery|infection|fracture|tear)\b", low))
    if questionnaire_only and not severe_signal:
        return False
    if event.event_type.value in {"office_visit", "pt_visit", "inpatient_daily_note"} and meaningful_clinic_signal:
        return True

    if event.event_type.value in {"office_visit", "pt_visit", "inpatient_daily_note"} and re.search(r"\b(admission|discharge|assessment|impression|diagnosis|procedure|surgery|infection|fracture|tear|medication|started|stopped|increased|decreased|switched|plan|disposition|hospice|snf)\b", low):
        return True
    return False

def classify_projection_entry(entry: ChronologyProjectionEntry) -> str:
    et = (entry.event_type_display or "").lower()
    facts = " ".join(entry.facts).lower()
    if is_ed_event(text_blob=facts, event_type=et, provider_blob=(entry.provider_display or "")):
        return "ed_visit"
    if is_flowsheet_noise(" ".join(entry.facts or [])):
        return "flowsheet"
    if "admission" in et:
        return "inpatient"
    if "discharge" in et:
        return "discharge_transfer"
    if "emergency" in et or "er visit" in et or re.search(r"\bemergency room|ed visit\b", facts):
        return "ed_visit"
    if "procedure" in et or "surgery" in et:
        return "surgery_procedure"
    if "imaging" in et:
        return "imaging_impression"
    if "therapy" in et:
        return "therapy"
    if "lab" in et:
        return "labs"
    if re.search(r"\b(phq-?9|gad-?7|questionnaire|survey score|promis|pain interference)\b", facts):
        return "questionnaire"
    if re.search(r"\b(body height|body weight|blood pressure|respiratory rate|heart rate|temperature|bmi|weight percentile)\b", facts):
        return "vitals"
    if re.search(r"\b(intake|demographic|insurance|education|income|tobacco status)\b", facts):
        return "admin"
    if "follow-up visit" in et or "inpatient progress" in et:
        return "clinic"
    return "other"

def bucket_for_required_coverage(entry: ChronologyProjectionEntry) -> str | None:
    event_class = classify_projection_entry(entry)
    blob = " ".join(entry.facts).lower()
    et = (entry.event_type_display or "").lower()
    cite = (entry.citation_display or "").lower()
    provider = (entry.provider_display or "").lower()
    if event_class == "flowsheet":
        return None

    pt_context = (
        ("therapy" in et)
        or bool(re.search(r"\b(physical therapy|pt|therap)\b", provider))
        or bool(re.search(r"\b(pt eval|physical therapy|rehab|therap)\b", cite))
        or bool(re.search(r"\b(physical therapy|pt evaluation|plan of care|therapeutic exercise|manual therapy)\b", blob))
    )
    ed_context = is_ed_event(text_blob=blob, event_type=et, provider_blob=provider, event_class=event_class)
    if re.search(r"\b(ortho|orthopedic)\b", blob):
        return "ortho"
    if ed_context or _MECHANISM_MARKER_RE.search(blob):
        return "ed"
    if event_class == "imaging_impression":
        if re.search(r"\bmri\b", blob):
            return "mri"
        return "xr_radiology"
    if event_class == "therapy":
        if pt_context and (
            re.search(r"\b(initial evaluation|pt evaluation|evaluation|eval|plan of care)\b", blob)
            or re.search(r"\bpt[_ -]?eval|initial[_ -]?eval|plan[_ -]?of[_ -]?care\b", cite)
        ):
            return "pt_eval"
        if pt_context and re.search(r"\bassessment\b", blob) and re.search(r"\b(initial|evaluation|eval|plan of care|goals?|functional limitation|adl)\b", blob):
            return "pt_eval"
        return "pt_followup"
    if event_class == "surgery_procedure":
        return "procedure"
    if "follow-up visit" in et and re.search(r"\b(work status|work restriction|return to work|pcp|primary care|referral)\b", blob):
        return "pcp_referral"
    if re.search(r"\b(total billed|balance|ledger|billing)\b", blob):
        return "billing"
    return None

def projection_entry_score(entry: ChronologyProjectionEntry) -> int:
    event_class = classify_projection_entry(entry)
    base = {
        "inpatient": 90, "discharge_transfer": 90, "ed_visit": 85, "surgery_procedure": 85, "imaging_impression": 75, "therapy": 55, "clinic": 35, "labs": 30, "questionnaire": 10, "vitals": 10, "flowsheet": 0, "admin": 0, "other": 20,
    }[event_class]
    facts = " ".join(entry.facts).lower()
    severe_score = False
    for m in re.finditer(r"\b(phq-?9|gad-?7|pain(?:\s+severity|\s+score)?)\s*[:=]?\s*(\d{1,2})\b", facts):
        try:
            if int(m.group(2)) >= 15:
                severe_score = True
                break
        except ValueError:
            continue
    if re.search(r"\b(disposition|discharged|skilled nursing|snf|hospice|return to work|work restriction|follow-?up)\b", facts):
        base += 15
    if re.search(r"\b(new|newly|started|initiated|stopped|discontinued|increased|decreased|switched|changed to)\b", facts):
        base += 15
    if severe_score:
        base += 10
    if re.search(r"\b(left|right|bilateral)\b.*\b(fracture|tear|injury|dislocation|infection|pain|wound)\b|\b(fracture|tear|injury|dislocation|infection|pain|wound)\b.*\b(left|right|bilateral)\b", facts):
        base += 10
    if event_class == "labs":
        if re.search(r"\b(critical|panic|high-risk|abnormal|elevated)\b", facts):
            base += 20
        else:
            base -= 10
    if event_class == "clinic" and not re.search(r"\b(assessment|impression|diagnosis|procedure|surgery|infection|fracture|tear|medication|started|stopped|increased|decreased|switched|plan|disposition|hospice|snf|admission|discharge)\b", facts):
        base -= 20
    if re.search(r"\b(tobacco status|never smoked|weight percentile|body weight|body height|blood pressure)\b", facts):
        base -= 20
    if re.search(r"\bclinical follow-?up documenting continuity, symptoms, and treatment response\b", facts):
        base -= 30
    if not (entry.citation_display or "").strip():
        base -= 15
    return max(0, min(100, base))

def entry_substance_score(entry: ChronologyProjectionEntry) -> int:
    facts = " ".join(entry.facts).lower()
    if not (entry.citation_display or "").strip():
        return 0
    score = _mechanism_priority_score(facts)
    if re.search(r"\b(diagnosis|assessment|impression|problem|radiculopathy|fracture|tear|infection|stenosis|sprain|strain)\b", facts):
        score += 2
    if re.search(r"\b(surgery|operative|procedure|debridement|orif|arthroplasty|repair|reconstruction|injection|epidural|nerve block|medrol|lidocaine|marcaine|depo)\b", facts):
        score += 3
    if re.search(r"\b(mri|ct\s+scan|x-ray|radiograph|ultrasound|sonogram|imaging|angiogram|myelogram)\b", facts):
        score += 2
    if re.search(r"\bimpression\b", facts):
        score += 2
    if re.search(r"\b(hydrocodone|oxycodone|morphine|tramadol|fentanyl|acetaminophen|ibuprofen|naproxen|lisinopril|metformin)\b.*\b\d+(?:\.\d+)?\s*(mg|mcg|ml)\b", facts):
        score += 2
    if re.search(r"\b(rom|range of motion|strength|pain\s*(?:score|severity)?|blood pressure|heart rate|respiratory rate|temperature)\b.*\b\d", facts):
        score += 2
    if re.search(r"\b(depo-?medrol|lidocaine|fluoroscopy|interlaminar|transforaminal|epidural|esi|procedure|surgery)\b", facts):
        score += 2
    if re.search(r"\b(work restriction|return to work|work status)\b", facts):
        score += 2
    if re.search(r"\b(emergency|chief complaint|clinical impression|hpi|history of present illness)\b", facts):
        score += 2
    if re.search(r"\b(disc protrusion|radicular|foramen|thecal sac|ortho|orthopedic)\b", facts):
        score += 2
    if re.search(r"\bpain\b[^0-9]{0,10}\d{1,2}\s*(?:/10)?\b", facts):
        score += 2
    if re.search(r"\b(follow-?up|evaluation|re-?evaluation|consult|discharge summary|plan of care|functional limitation|adl)\b", facts):
        score += 1
    if re.search(r"\b(limited detail|encounter recorded|continuity of care|documentation noted)\b", facts):
        score -= 3
    if any(getattr(entry, "verbatim_flags", [])):
        score += 5
    return max(0, score)

def is_substantive_entry(entry: ChronologyProjectionEntry) -> bool:
    if not (entry.citation_display or "").strip():
        return False
    if any(getattr(entry, "verbatim_flags", [])):
        return True
    event_class = classify_projection_entry(entry)
    if event_class == "flowsheet":
        return False
    if event_class in {"ed_visit", "imaging_impression", "surgery_procedure", "inpatient", "discharge_transfer"}:
        return True
    if event_class == "therapy":
        facts = " ".join(entry.facts).lower()
        category_hits = 0
        if re.search(r"\bpain(?:\s*(?:score|severity|level))?\s*[:=]?\s*\d{1,2}\s*/\s*10\b", facts):
            category_hits += 1
        if re.search(r"\b(rom|range of motion)\b.*\b\d+\s*deg\b|\b\d+\s*deg\b", facts):
            category_hits += 1
        if re.search(r"\bstrength\b.*\b[0-5](?:\.\d+)?\s*/\s*5\b|\b[0-5](?:\.\d+)?\s*/\s*5\b", facts):
            category_hits += 1
        if re.search(r"\b(work restriction|return to work|functional limitation|adl)\b", facts):
            category_hits += 1
        if category_hits >= 2:
            return True
    return entry_substance_score(entry) >= MIN_SUBSTANCE_THRESHOLD
